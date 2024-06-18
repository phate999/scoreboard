from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, Response

import magic

from typing import List, Optional

from db import (
    User, 
    ApplicationCreate,
    Applications,
    ApplicationAssignment, 
    ApplicationAssignmentCreate, 
    Submission, 
    SubmissionCreate, 
    Attachment,
    create_db_and_tables, 
    async_session_maker
)
from sqlalchemy import select
from schemas import UserCreate, UserRead, UserUpdate
import uuid
import hashlib
from users import cookie_auth_backend, api_auth_backend, current_active_user, current_active_user_optional, fastapi_users
from saml import router as saml_router

from PIL import Image
import io
import os

MAX_UPLOAD_SIZE = 1024 * 1024 * 4 # 4MB

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Not needed if you setup a migration system like Alembic
    await create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

app.include_router(
    fastapi_users.get_auth_router(api_auth_backend), prefix="/auth/jwt-api", tags=["auth"]
)
app.include_router(
    fastapi_users.get_auth_router(cookie_auth_backend), prefix="/auth/jwt", tags=["auth"]
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
app.include_router( 
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

app.include_router(saml_router)

#api to create a new application
@app.post("/applications")
async def create_application(application: ApplicationCreate, user: User = Depends(current_active_user)):
    # active user must be superuser
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="User is not superuser")

    # create a new Application instance
    new_application = Applications(name=application.name, is_active=application.is_active)

    # populate the application in the database
    
    async with async_session_maker() as session:
        try:
            # add the new application to the session
            session.add(new_application)

            # commit the transaction
            await session.commit()

            # refresh the instance in case any attributes have been modified on the server side
            await session.refresh(new_application)

            return {"message": "Application created successfully", "application": new_application.id}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=400, detail="Could not create application") from e
        finally:
            await session.close()

@app.put("/applications/{application_id}")
async def update_application(application_id: int, application_update: ApplicationCreate, user: User = Depends(current_active_user)):
    # active user must be superuser
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="User is not superuser")

    # fetch the application from the database
    async with async_session_maker() as session:
        result = await session.execute(select(Applications).where(Applications.id == application_id))
        application = result.scalars().first()

        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        # update the application attributes
        application.name = application_update.name
        application.is_active = application_update.is_active
        application.description = application_update.description
        application.instructions = application_update.instructions
        # commit the transaction
        await session.commit()

        return {"message": "Application updated successfully", "application": application.id}

@app.get("/applications")
async def get_applications(user: User = Depends(current_active_user)):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="User is not superuser")
    # fetch all applications
    async with async_session_maker() as session:
        result = await session.execute(select(Applications))
        applications = result.scalars().all()
        return {"applications": applications}

@app.get("/applications/me")
async def get_applications(user: User = Depends(current_active_user)):
    # fetch all assigned applications
    async with async_session_maker() as session:
        # query the ApplicationAssignment table
        result = await session.execute(
            select(ApplicationAssignment, Applications).
            join(Applications, ApplicationAssignment.application_id == Applications.id).
            where(ApplicationAssignment.user_id == user.id))
        rows = result.all()
        assignments = [
            {
                "user_id": assignment.user_id,
                "application_id": assignment.application_id,
                "is_admin": assignment.is_admin,
                "application": {
                    "name": application.name,
                    "id": application.id,
                    "description": application.description,
                    "instructions": application.instructions
                }
            } for assignment, application in rows   
        ]
        return {"application_assignments": assignments}

@app.post("/application_assignments")
async def assign_application(application_assignment: ApplicationAssignmentCreate, user: User = Depends(current_active_user)):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="User is not superuser")

    async with async_session_maker() as session:
        try:
            # create a new ApplicationAssignment instance
            new_assignment = ApplicationAssignment(user_id=application_assignment.user_id, application_id=application_assignment.application_id)

            # add the new assignment to the session
            session.add(new_assignment)

            # commit the transaction
            await session.commit()

            # refresh the instance in case any attributes have been modified on the server side
            await session.refresh(new_assignment)

            return {"message": "Application assigned successfully", "user_id": new_assignment.user_id, "application_id": new_assignment.application_id}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=400, detail="Could not assign application") from e
        finally:
            await session.close()

@app.post("/application_submission")
async def application_submission(submission: SubmissionCreate, user: User = Depends(current_active_user)):
    async with async_session_maker() as session:
        try:
            # create a new Submission instance
            new_submission = Submission(application_id=submission.application_id, user_id=user.id, submission=submission.submission, attachments=submission.attachments)

            # add the new submission to the session
            session.add(new_submission)

            # commit the transaction
            await session.commit()

            # refresh the instance in case any attributes have been modified on the server side
            await session.refresh(new_submission)

            return {"message": "Submission created successfully", "submission_id": new_submission.id}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=400, detail="Could not create submission") from e
        finally:
            await session.close()

@app.get("/application_submission")
async def get_application_submission(application_id: Optional[int] = None, user: User = Depends(current_active_user)):
    async with async_session_maker() as session:
        # Create a query that selects all submissions for the current user
        query = select(Submission).where(Submission.user_id == user.id)

        # If an application ID was provided, add a filter for it to the query
        if application_id is not None:
            query = query.where(Submission.application_id == application_id)

        # Execute the query
        result = await session.execute(query)
        submissions = result.scalars().all()

        return {"submissions": submissions}

@app.delete("/application_submission/{submission_id}")
async def delete_application_submission(submission_id: int, user: User = Depends(current_active_user)):
    async with async_session_maker() as session:
        result = await session.execute(select(Submission).where(Submission.id == submission_id))
        submission = result.scalars().first()
        if submission is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission.user_id != user.id:
            raise HTTPException(status_code=403, detail="User does not have access to this submission")
        await session.delete(submission)
        await session.commit()
    return {"message": "Submission deleted successfully"}

@app.post("/upload_attachment")
async def upload_attachment(fileAttach: List[UploadFile] = Form(...), desc: str = Form(...), user: User = Depends(current_active_user)):
    uuids = []
    for attachment in fileAttach:
        if attachment.filename == "":
            continue
        attachment_file = await attachment.read()

        if len(attachment_file) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"File size too large. Max file size is {MAX_UPLOAD_SIZE} bytes")

        mime_type = magic.from_buffer(attachment_file, mime=True)

        if mime_type not in ["image/jpeg", "image/png"]:
            raise HTTPException(status_code=400, detail="Only image/jpeg and image/png are allowed")

        file_hash = hashlib.sha256(attachment_file).hexdigest()
        file_uuid = uuid.UUID(file_hash[:32])

        with open(f"data/{file_uuid}.{mime_type.split('/')[-1]}", "wb") as f:
            f.write(attachment_file)

        # Open the image and create a thumbnail
        image = Image.open(io.BytesIO(attachment_file))
        image.thumbnail((128, 128))  # Resize the image so that the largest dimension is 128 pixels

        # Convert the image to RGB mode if it's not
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        # Save the thumbnail
        thumbnail_path = f"data/{file_uuid}_thumbnail.jpg"
        image.save(thumbnail_path, "JPEG")

        async with async_session_maker() as session:
            try:
                # create a new Attachment instance
                new_attachment = Attachment(mime_type=mime_type, user_id=user.id, desc=desc, id=file_uuid)

                # add the new attachment to the session
                session.add(new_attachment)

                # commit the transaction
                await session.commit()

                # refresh the instance in case any attributes have been modified on the server side
                await session.refresh(new_attachment)
            except Exception as e:
                await session.rollback()
                raise HTTPException(status_code=400, detail="Could not create attachment") from e
            finally:
                await session.close()
        uuids.append(file_uuid)
    return {"message": "Attachment uploaded successfully", "uuids": uuids}

@app.get("/attachments/data/{attachment_id_with_suffix}")
async def get_attachment(attachment_id_with_suffix: str, user: User = Depends(current_active_user)):
    thumbnail = False
    if attachment_id_with_suffix.endswith("_thumbnail.jpg"):
        attachment_id = attachment_id_with_suffix[:-len("_thumbnail.jpg")]
        thumbnail = True
    else:
        attachment_id = attachment_id_with_suffix
    try:
        attachment_id = uuid.UUID(attachment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attachment id")
    async with async_session_maker() as session:
        result = await session.execute(select(Attachment).where(Attachment.id == attachment_id))
        attachment = result.scalars().first()
        if attachment is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        if attachment.user_id != user.id:
            raise HTTPException(status_code=403, detail="User does not have access to this attachment")
        filename = f"data/{attachment_id}_thumbnail.jpg" if thumbnail else f"data/{attachment_id}.{attachment.mime_type.split('/')[-1]}"
        media_type = "image/jpeg" if thumbnail else attachment.mime_type
        return FileResponse(filename, media_type=media_type)

@app.get("/login")
async def login(request: Request, current_user: User = Depends(current_active_user_optional)):
    if current_user is None:
        showpoint_sso = os.environ.get("SHOWPOINT_SSO_URL")
        return templates.TemplateResponse("login.html", {"request": request, "showpoint_sso": showpoint_sso})
    return RedirectResponse(url="/", status_code=303)

@app.get("/")
async def root(request: Request, current_user: User = Depends(current_active_user_optional)):
    if current_user is None:
        return templates.TemplateResponse("needs_login.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request, "username": current_user.email})

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)