"""exceptions.py —— 业务异常家族。

为什么单独建文件：业务层抛"业务异常"，HTTP 翻译交给 handler，
这样 service 不依赖 FastAPI，以后被命令行/定时任务复用也不尴尬。
"""

class AppException(Exception):
    """所有业务异常的基类。

    只存两个东西：给用户看的话（detail）、这个错误对应的 HTTP 状态码。
    """

    def __init__(self, detail: str):
        # TODO: 把 detail 存成 self.detail
        self.detail = detail
        # TODO: 调用父类 Exception 的初始化（把 detail 传给 Exception，
        #        这样 str(e) / print(e) 能直接看到消息）
        super().__init__(detail)
        
class NotFoundError(AppException):
    """资源不存在。将来翻译成 404。"""

    # TODO: 子类只做一件事——把 status_code 定死为 404
    status_code = 404

class PermissionDeniedError(AppException):
    """无权限。将来翻译成 403。"""

    # TODO: 子类只做一件事——把 status_code 定死为 403
    status_code = 403

class ConflictError(AppException):
    """资源冲突（如注册重名）。将来翻译成 409。"""

    status_code = 409