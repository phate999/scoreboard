from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from onelogin.saml2.auth import OneLogin_Saml2_Auth

import secrets
import os
from users import get_user_by_email, manual_register, manual_login, UserCreate

router = APIRouter(
    prefix="/saml",
    tags=["saml"]
)

saml_certificate = os.environ.get("SAML_CERTIFICATE")
saml_hostname = os.environ.get("HOSTNAME")
saml_aws_app = os.environ.get("SAML_AWS_APP")
saml_settings = {
    "strict": True, 
    "debug": True,
    "sp": {
        "entityId": f"https://{saml_hostname}/saml/metadata",
        "assertionConsumerService": {
            "url": f"https://{saml_hostname}/saml/acs",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        },
        "singleLogoutService": {
            "url": f"https://{saml_hostname}/saml/sls",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
    },
    "idp": {
        "entityId": f"https://portal.sso.us-west-1.amazonaws.com/saml/assertion/{saml_aws_app}",
        "singleSignOnService": {
            "url": f"https://portal.sso.us-west-1.amazonaws.com/saml/assertion/{saml_aws_app}",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "singleLogoutService": {
            "url": f"https://portal.sso.us-west-1.amazonaws.com/saml/logout/{saml_aws_app}",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "x509cert": f"{saml_certificate}"
  },

    "security": {
        "authnRequestsSigned": False,
        "wantAssertionsSigned": False,
        "wantMessagesSigned": False,
        "wantAssertionsEncrypted": False,
        "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256"
    }
}

def init_saml_auth(req):
    auth = OneLogin_Saml2_Auth(req, saml_settings)
    return auth

async def prepare_fastapi_request(request: Request):
    rval = {
        'https': 'on' if request.url.scheme == 'https' else 'off',
        'http_host': request.url.hostname,
        'server_port': str(request.url.port) if request.url.port else '443',
        'script_name': request.url.path,
        'get_data': dict(request.query_params),
        'post_data': dict(await request.form()) if request.method == 'POST' else {}
    }
    return rval

@router.get("/login")
async def saml_login(request: Request):
    req = await prepare_fastapi_request(request)
    auth = init_saml_auth(req)
    login = auth.login()
    return RedirectResponse(login)

@router.post("/acs")
async def saml_acs(request: Request):
    req = await prepare_fastapi_request(request)
    auth = init_saml_auth(req)
    auth.process_response()
    errors = auth.get_errors()
    if len(errors) == 0:
        if auth.is_authenticated():
            # Extract user information from SAML response
            user_attributes = auth.get_attributes()
            email = user_attributes.get("email", [None])[0]
            
            # Retrieve or create user in your database
            user = await get_user_by_email(email)
            if user is None:
                # Create user if not exists
                user_create = UserCreate(email=email, password=secrets.token_hex(32))
                user = await manual_register(request, user_create)
            
            resp = await manual_login(user)
            return RedirectResponse(url="/", status_code=303, headers=resp.headers)
        else:
            return Response(content=f"User is not authenticated", status_code=400)
    else:
        return Response(content=f"Error when processing SAML Response: {', '.join(errors)}", status_code=400)

@router.get("/metadata")
async def saml_metadata(request: Request):
    req = prepare_fastapi_request(request)
    auth = init_saml_auth(req)
    settings = auth.get_settings()
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if len(errors) == 0:
        return Response(content=metadata, media_type="application/xml")
    else:
        return Response(content=f"Error when processing SAML Metadata: {', '.join(errors)}", status_code=400)