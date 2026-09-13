"""documents/routes.py —— 文档的 HTTP 端点（路由层，只接线不干业务）。"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from loguru import logger

from app.config import settings
from app.db.main import SessionDep, async_session
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


async def process_document(document_id: uuid.UUID, temp_path: Path, thread_id: uuid.UUID) -> None:
    """后台：索引进向量库 → 更新状态。请求已返回，用户不等待。"""
    async with async_session() as session:  # 后台任务没有请求的 session，自己开
        try:
            chunk_count = await index_document(temp_path, document_id, thread_id)
            await document_service.update_status(document_id, "ready", session)
            logger.info(f"处理完成: {document_id} → {chunk_count} 个切片")
        except Exception as e:
            await document_service.update_status(document_id, "failed", session, error_message=str(e)[:500])
            logger.exception("文档处理失败")
        finally:
            # 临时文件的生命周期延伸到这：后台读完才删（请求返回时文件还在）
            if temp_path.exists():
                temp_path.unlink()


@document_router.get("/{thread_id}", response_model=list[DocumentPublic])
async def get_documents(thread_id: uuid.UUID, session: SessionDep, current_user: str = Depends(get_current_user)):
    """列出该会话下的所有文档（只允许列自己的会话）。"""
    return await document_service.get_documents(thread_id, uuid.UUID(current_user), session)


@document_router.post(
    "/upload/{thread_id}",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    thread_id: uuid.UUID,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: str = Depends(get_current_user),
):
    """上传文档：临时落盘 → 登记数据库 → 预约后台索引进向量库（立即返回 202）。"""
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

        # ⑤ 先登记数据库（拿 document_id，status 默认 processing，后台任务再去更新它）
        document_data = DocumentBase(file_name=file.filename, thread_id=thread_id)
        new_document = await document_service.insert_document(document_data, session)
        document_id = new_document.id

        # ⑥ 预约后台任务：响应先返回（202），处理在后台慢慢跑
        background_tasks.add_task(process_document, new_document.id, temp_path, thread_id)
        logger.info(f"已接收上传，后台处理中: {file.filename}")
        return DocumentUploadResponse(
            document_id=document_id,
            message=f"File {file.filename} received, processing in background.",
            file_name=file.filename,
            thread_id=thread_id,
        )
    except HTTPException:
        raise  # 用户侧错误（400/413）原样透传——别吞成 500，前端要拿真实原因
    except Exception as e:
        # ⑦ 回滚：请求内失败，后台任务没接管——数据库登记了就清掉，临时文件也删
        if document_id is not None:
            try:
                await delete_document_chunks(document_id)   # 清向量库（可能没进，幂等安全）
                await document_service.delete_document(document_id, session)  # 清数据库
            except Exception:
                logger.exception("回滚失败")
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传失败: {file.filename}",
        ) from e


@document_router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(document_id: uuid.UUID, session: SessionDep, current_user: str = Depends(get_current_user)):
    """删除文档：先清向量库切片，再删数据库记录（只允许删自己会话的）。"""
    await delete_document_chunks(document_id)  # Chroma 按 document_id 清片（查不到就空操作）
    await document_service.delete_document(document_id, uuid.UUID(current_user), session)  # 归属校验在 service，不存在/不是你的 404
    return DocumentDeleteResponse(message=f"成功删除文档 {document_id}（含向量库切片）")
