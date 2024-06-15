from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from typing import List

from db import (
    User, 
    ApplicationCreate,
    Applications,
    ApplicationAssignment, 
    ApplicationAssignmentCreate, 
    Submission, 
    SubmissionCreate, 
    Attachment,
    AttachmentCreate,
    create_db_and_tables, 
    async_session_maker
)
from sqlalchemy import select
from schemas import UserCreate, UserRead, UserUpdate
import uuid
import hashlib
from users import cookie_auth_backend, api_auth_backend, current_active_user, current_active_user_optional, fastapi_users

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
        print(application_update)
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
    print(application_assignment, application_assignment.user_id, application_assignment.application_id)
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
            print(e)
            await session.rollback()
            raise HTTPException(status_code=400, detail="Could not assign application") from e
        finally:
            await session.close()

@app.post("/application_submission")
async def application_submission(submission: SubmissionCreate, user: User = Depends(current_active_user)):

    async with async_session_maker() as session:
        try:
            # create a new Submission instance
            new_submission = Submission(application_id=submission.application_id, user_id=current_active_user.user_id, submission=submission.submission, attachements=submission.attachements)

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

@app.post("/upload_attachment")
async def upload_attachment(fileAttach: List[UploadFile] = File(...), desc: str = Form(...), user: User = Depends(current_active_user)):
    # form = await request.form()
    # fetch the attachements from the form
    # attachements = form["fileAttach"]
    print("fileattach", fileAttach)
    
    # desc = form.get("desc")
    print("desc", desc) # todo try to pass this in as an argument
    uuids = []
    for attachement in fileAttach:
        attachement_file = await attachement.read()
        file_hash = hashlib.sha256(attachement_file).hexdigest()
        file_uuid = uuid.UUID(file_hash[:32])
        with open(f"data/{file_uuid}", "wb") as f:
            f.write(attachement_file)
        async with async_session_maker() as session:
            try:
                # create a new Attachment instance
                new_attachment = Attachment(user_id=user.id, desc=desc, id=file_uuid)
                print(new_attachment)

                # add the new attachment to the session
                session.add(new_attachment)

                # commit the transaction
                await session.commit()

                # refresh the instance in case any attributes have been modified on the server side
                await session.refresh(new_attachment)
            except Exception as e:
                print(e)
                await session.rollback()
                raise HTTPException(status_code=400, detail="Could not create attachment") from e
            finally:
                await session.close()
        uuids.append(file_uuid)
    return {"message": "Attachment uploaded successfully", "uuids": uuids}

@app.get("/authenticated-route")
async def authenticated_route(user: User = Depends(current_active_user)):
    return {"message": f"Hello {user.email}!"}

@app.get("/login")
async def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/")
async def root(request: Request, current_user: User = Depends(current_active_user_optional)):
    if current_user is None:
        return templates.TemplateResponse("needs_login.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request, "username": current_user.email})