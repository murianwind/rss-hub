"""피드 가져오기 화면: 파일 올리기 → 미리보기 → 확정 또는 취소.

- 올린 파일의 내용은 화면에 되돌려 주지 않는다(오류 메시지는 정해진 문구뿐이다).
- 크기는 헤더로 먼저 확인하고, 읽을 때도 제한을 둔다.
- 피드의 사이트 주소는 글자로만 보여 주고 링크로 만들지 않는다(javascript: 같은 주소 방지).
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from rss_hub.domain.importing import MAX_UPLOAD_BYTES, PRESETS, STATUS_NEW, ImportFileError
from rss_hub.services.importer import ImportChoices, ImportService, PreviewExpired

# 멀티파트 형식의 머리말과 경계 문자열 몫으로 5MB에 더해 주는 여유
UPLOAD_OVERHEAD = 200_000
TOO_LARGE = "파일이 너무 큼(최대 5MB)"
NO_FILE = "파일을 선택해 주세요"


def build_import_router(importer: ImportService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request, *, error: str = "", notice: str = "", status_code: int = 200
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "import.html", {"error": error, "notice": notice}, status_code=status_code
        )

    @router.get("/import", response_class=HTMLResponse)
    def import_page(request: Request, cancelled: str = "") -> HTMLResponse:
        return page(
            request, notice="취소했습니다. 구독 목록은 바뀌지 않았습니다." if cancelled else ""
        )

    @router.post("/import/preview", response_class=HTMLResponse)
    async def preview(request: Request) -> Response:
        declared = int(request.headers.get("content-length") or 0)
        if declared > MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD:
            return page(request, error=TOO_LARGE, status_code=413)
        form = await request.form(max_files=1, max_fields=20)
        try:
            upload = form.get("file")
            if not isinstance(upload, UploadFile) or not upload.filename:
                return page(request, error=NO_FILE, status_code=400)
            filename = upload.filename
            data = await upload.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await form.close()  # 업로드 임시 파일을 바로 닫는다(수거를 기다리지 않는다)
        try:
            stored = importer.preview(filename, data)
        except ImportFileError as error:
            return page(request, error=error.message, status_code=400)

        context: dict[str, Any] = {
            "token": stored.token,
            "preview": stored.preview,
            "new_status": STATUS_NEW,
            "preset_labels": {key: preset.label for key, preset in PRESETS.items()},
        }
        return templates.TemplateResponse(request, "import_preview.html", context)

    @router.post("/import/confirm", response_class=HTMLResponse)
    async def confirm(request: Request) -> Response:
        form = await request.form(max_fields=5000)
        token = str(form.get("token", ""))
        try:
            preview_data = importer.load(token)
            presets = {
                item.index: form.get(f"preset_{item.index}") == "yes"
                for item in preview_data.items
                if item.preset
            }
            result = importer.confirm(
                token,
                ImportChoices(
                    import_categories=form.get("import_categories") == "yes",
                    presets=presets,
                ),
            )
        except PreviewExpired as error:
            return page(request, error=error.message, status_code=400)
        return templates.TemplateResponse(request, "import_done.html", {"result": result})

    @router.post("/import/cancel", response_class=HTMLResponse)
    async def cancel(request: Request) -> Response:
        form = await request.form()
        importer.cancel(str(form.get("token", "")))
        return RedirectResponse("/import?cancelled=1", status_code=303)

    return router
