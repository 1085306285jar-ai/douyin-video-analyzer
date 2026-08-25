from __future__ import annotations


class AnalyzerError(Exception):
    """Base class for errors that are safe to show to the user."""

    user_message = "处理失败，请稍后重试。"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        self.user_message = message or self.user_message


class InvalidLinkError(AnalyzerError):
    user_message = "没有识别到有效的抖音链接。"


class UnsupportedLinkError(AnalyzerError):
    user_message = "暂不支持这个链接，请粘贴抖音单视频、合集或博主主页链接。"


class DependencyMissingError(AnalyzerError):
    user_message = "程序组件不完整，请重新下载官方完整版本。"


class ModelMissingError(AnalyzerError):
    user_message = "本地语音模型缺失，请重新下载官方完整版本。"


class ExtractionError(AnalyzerError):
    user_message = "无法读取该抖音内容。"


class AuthenticationRequiredError(ExtractionError):
    user_message = "该内容要求登录或平台验证，已跳过。"


class PrivateContentError(ExtractionError):
    user_message = "该内容不是公开内容，已跳过。"


class ContentUnavailableError(ExtractionError):
    user_message = "该内容已失效、被删除或当前地区不可用。"


class NetworkError(ExtractionError):
    user_message = "网络连接抖音失败，请检查网络后重试。"


class NoSpeechError(AnalyzerError):
    user_message = "没有检测到有效口播内容。"


class CancelledError(AnalyzerError):
    user_message = "任务已取消。"


class ExportError(AnalyzerError):
    user_message = "结果保存失败，请检查磁盘空间或文件夹权限。"
