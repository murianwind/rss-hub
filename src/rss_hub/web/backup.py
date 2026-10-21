"""백업과 복원 화면. 내려받기는 GET, 복원은 파일 올리기(확인 표시 필수)다.

- 파일 내용은 화면에 되돌려 주지 않는다(오류 문구는 정해진 것뿐이다).
- 크기는 헤더로 먼저 확인하고, 읽을 때도 제한을 둔다.
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from rss_hub.domain.backup import MAX_BACKUP_BYTES, BackupError
from rss_hub.services.backup import BackupService

UPLOAD_OVERHEAD = 200_000  # 멀티파트 머리말과 경계 문자열 몫
TOO_LARGE = "파일이 너무 큼(최대 100MB)"
NO_FILE = "파일을 선택해 주세요"
NOT_CONFIRMED = "현재 데이터가 모두 바뀐다는 확인 표시가 필요함"


def build_backup_router(service: BackupService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def result_page(
        request: Request, *, error: str = "", result: Any = None, status_code: int = 200
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "backup_result.html",
            {"error": error, "result": result},
            status_code=status_code,
        )

    @router.get("/backup", response_class=HTMLResponse)
    def backup_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "backup.html", {})

    @router.get("/backup/export")
    def export() -> Response:
        filename, chunks = service.export()
        return StreamingResponse(
            chunks,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/backup/restore", response_class=HTMLResponse)
    async def restore(request: Request) -> Response:
        declared = int(request.headers.get("content-length") or 0)
        if declared > MAX_BACKUP_BYTES + UPLOAD_OVERHEAD:
            return result_page(request, error=TOO_LARGE, status_code=413)
        form = await request.form(max_files=1, max_fields=10)
        try:
            if form.get("confirm") != "yes":
                return result_page(request, error=NOT_CONFIRMED, status_code=400)
            upload = form.get("file")
            if not isinstance(upload, UploadFile) or not upload.filename:
                return result_page(request, error=NO_FILE, status_code=400)
            data = await upload.read(MAX_BACKUP_BYTES + 1)
        finally:
            await form.close()
        if len(data) > MAX_BACKUP_BYTES:
            return result_page(request, error=TOO_LARGE, status_code=413)
        try:
            result = service.restore(data)
        except BackupError as error:
            return result_page(request, error=error.message, status_code=400)
        return result_page(request, result=result)

    return router
