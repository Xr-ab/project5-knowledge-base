"""documents/routes.py —— 文档的 HTTP 端点（路由层，只接线不干业务）。"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from loguru import logger

from app.config import settings
from app.db.main import SessionDep
from app.db.vector_store import SUPPORTED_EXTENSIONS, delete_document_chunks, index_document
from app.documents import service as document_service
from app.documents.schemas import (
    DocumentBase,
    DocumentDeleteResponse,
    DocumentPublic,
    DocumentUploadResponse,
)
from app.security import get_current_user  # 登录依赖：没带合法 token 一律 401

document_router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 上传上限 10MB（规范 §7.4；可调参数，v1 先放常量）


@document_router.get("/{thread_id}", response_model=list[DocumentPublic])
async def get_documents(thread_id: uuid.UUID, session: SessionDep, current_user: str = Depends(get_current_user)):
    """列出该会话下的所有文档（只允许列自己的会话）。"""
    return await document_service.get_documents(thread_id, uuid.UUID(current_user), session)


@document_router.post(
    "/upload/{thread_id}",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(thread_id: uuid.UUID, file: UploadFile, session: SessionDep, current_user: str = Depends(get_current_user)):
    """上传文档：临时落盘 → 登记数据库 → 索引进向量库；任何一步失败都回滚。"""
    # ⓪ 先验归属：权限都没有就不做任何活（不读文件、不碰磁盘）
    await document_service.ensure_thread_owned(thread_id, uuid.UUID(current_user), session)

    # ① 校验扩展名（早失败：不合法直接拒，不碰磁盘不做脏活）
    if file.filename is None or Path(file.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，允许: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = tmp_dir / file.filename
    document_id = None  # 是否已登记数据库——回滚的依据
    try:
        # ② 大小预判：用客户端声明的体积先拦一道，超大文件不白写磁盘（落盘后 stat 兜底，双保险）
        if file.size and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="文件超过 10MB 上限",
            )

        # ③ 临时落盘：向量库要读文件内容，先把请求流倒到磁盘
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # ④ 大小校验（§7.4）：落盘后的真实体积（客户端声明可能说谎，这是最终裁决）
        if temp_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="文件超过 10MB 上限",
            )

        # ⑤ 先登记数据库（拿 document_id，后面的索引要挂它）
        document_data = DocumentBase(file_name=file.filename, thread_id=thread_id)
        new_document = await document_service.insert_document(document_data, session)
        document_id = new_document.id

        # ⑥ 再索引进向量库（这一步失败 → 回滚：删掉刚登记的数据库记录）
        chunk_count = await index_document(temp_path, document_id, thread_id)
        logger.info(f"上传成功: {file.filename} → {chunk_count} 个切片")
        return DocumentUploadResponse(
            document_id=document_id,
            message=f"File {file.filename} uploaded and indexed successfully.",
            file_name=file.filename,  # 继承 DocumentBase → 这两个字段要补全
            thread_id=thread_id,
        )
    except HTTPException:
        raise  # 用户侧错误（400/413）原样透传——别吞成 500，前端要拿真实原因
    except Exception as e:
        # ⑦ 回滚：两个存储必须一致——数据库登记了但索引失败，就清掉数据库
        if document_id is not None:
            try:
                await delete_document_chunks(document_id)   # 清向量库（可能没进，幂等安全）
                await document_service.delete_document(document_id, session)  # 清数据库
            except Exception:
                logger.exception("回滚失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传失败: {file.filename}",
        ) from e
    finally:
        # ⑧ 无论成败，临时文件都要删（finally 永远执行）
        if temp_path.exists():
            temp_path.unlink()


@document_router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(document_id: uuid.UUID, session: SessionDep, current_user: str = Depends(get_current_user)):
    """删除文档：先清向量库切片，再删数据库记录（只允许删自己会话的）。"""
    await delete_document_chunks(document_id)  # Chroma 按 document_id 清片（查不到就空操作）
    await document_service.delete_document(document_id, uuid.UUID(current_user), session)  # 归属校验在 service，不存在/不是你的 404
    return DocumentDeleteResponse(message=f"成功删除文档 {document_id}（含向量库切片）")
