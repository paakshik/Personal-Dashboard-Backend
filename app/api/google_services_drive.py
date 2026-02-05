from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.dependencies import get_current_user
from app.utils.file_ops import upload_bytes_to_drive
from typing import Any, Dict
router = APIRouter()
from app.config import logger, sentry_sdk

@router.post("/dashboard/upload")
async def upload_file(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    API Endpoint to upload files to Google Drive.

    This endpoint accepts a file stream, authenticates the user, and delegates
    the upload logic to the file_ops service.

    Args:
        file (UploadFile): The binary file to be uploaded.
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: Success status and the Google Drive web link.

    Raises:
        HTTPException (401): If the user has not connected their Google Drive.
        HTTPException (500): For any other server-side failures.
    """
    try:
        logger.info(
            f"📥 API: Received upload request from user {current_user.get('id')} for file: {file.filename}")

        file_content = await file.read()

        result = upload_bytes_to_drive(
            user_id=current_user["id"],
            file_content=file_content,
            filename=file.filename,
            content_type=file.content_type
        )

        logger.info(f"✅ API: Upload success for {file.filename}")

        # 3. Return Success Response
        return {
            "status": "success",
            "filename": file.filename,
            "link": result.get('webViewLink'),
            "fileId": result.get('id')
        }

    except RuntimeError as e:
        # Catch logic-specific errors (like missing tokens)
        error_msg = str(e)
        if "Google Drive access not configured" in error_msg:
            logger.warning(
                f"⛔ Auth failed for user {current_user.get('id')}: {error_msg}")
            raise HTTPException(
                status_code=401,
                detail="Google Drive access not configured. Please re-authenticate."
            )

        logger.error(f"❌ Runtime Error during upload: {error_msg}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Internal processing error")

    except Exception as e:
        logger.error(f"🔥 Critical API Error during upload: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500,
                            detail="Internal server error during upload")