from pathlib import Path

import os
import secrets
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

app = FastAPI()


@app.get("/")
def root():
    # Serve the existing frontend UI from the repo root.
    index_path = Path(__file__).resolve().parent / "index.html"
    return FileResponse(str(index_path))


LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "").strip()
LINKEDIN_SCOPES = os.getenv("LINKEDIN_SCOPES", "w_member_social r_liteprofile").strip()

LI_COOKIE_NAME = os.getenv("LINKEDIN_COOKIE_NAME", "li_access_token")
LI_STATE_COOKIE = os.getenv("LINKEDIN_STATE_COOKIE_NAME", "li_oauth_state")


def _require_linkedin_oauth_config() -> None:
    missing = []
    if not LINKEDIN_CLIENT_ID:
        missing.append("LINKEDIN_CLIENT_ID")
    if not LINKEDIN_CLIENT_SECRET:
        missing.append("LINKEDIN_CLIENT_SECRET")
    if not LINKEDIN_REDIRECT_URI:
        missing.append("LINKEDIN_REDIRECT_URI")
    if missing:
        raise HTTPException(status_code=500, detail=f"LinkedIn OAuth not configured: {', '.join(missing)}")


class LinkedInPostRequest(BaseModel):
    text: str


@app.post("/api/linkedin/post")
def post_to_linkedin(req: LinkedInPostRequest, request: Request):
    """
    Server-side LinkedIn posting.
    This avoids browser CORS issues and keeps tokens out of JS fetches to LinkedIn.
    """
    token = (request.cookies.get(LI_COOKIE_NAME) or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not connected to LinkedIn")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing text")

    timeout_s = 30
    try:
        p_res = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LinkedIn userinfo request failed: {e}")

    if not p_res.ok:
        detail = p_res.text[:1000] if p_res.text else "LinkedIn userinfo failed"
        raise HTTPException(status_code=p_res.status_code, detail=detail)

    try:
        profile = p_res.json()
        sub = profile.get("sub")
    except Exception:
        sub = None

    if not sub:
        raise HTTPException(status_code=400, detail="LinkedIn profile missing `sub`")

    urn = f"urn:li:person:{sub}"

    payload = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    try:
        post_res = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=payload,
            timeout=timeout_s,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LinkedIn ugcPosts request failed: {e}")

    if not post_res.ok:
        # LinkedIn errors are often JSON; fall back to text.
        try:
            detail = post_res.json()
        except Exception:
            detail = post_res.text[:1000] if post_res.text else "LinkedIn ugcPosts failed"
        raise HTTPException(status_code=post_res.status_code, detail=detail)

    try:
        body = post_res.json()
    except Exception:
        body = {}

    return {
        "status": "ok",
        "http_status": post_res.status_code,
        "id": body.get("id"),
    }


@app.get("/api/linkedin/status")
def linkedin_status(request: Request):
    """
    Returns whether the user is connected.
    """
    token = (request.cookies.get(LI_COOKIE_NAME) or "").strip()
    if not token:
        return {"connected": False}

    try:
        p_res = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except Exception:
        return {"connected": False}

    if not p_res.ok:
        return {"connected": False}

    try:
        profile = p_res.json()
        # LinkedIn returns various localized fields; try the common ones.
        name = profile.get("localizedFirstName") or profile.get("firstName", "") or ""
        last = profile.get("localizedLastName") or profile.get("lastName", "") or ""
        name = (name + " " + last).strip() or "LinkedIn User"
    except Exception:
        name = "LinkedIn User"

    return {"connected": True, "name": name}


@app.get("/api/linkedin/login")
def linkedin_login(request: Request):
    _require_linkedin_oauth_config()

    state = secrets.token_urlsafe(16)
    secure_cookie = request.url.scheme == "https"

    params = {
        "response_type": "code",
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": LINKEDIN_REDIRECT_URI,
        "scope": LINKEDIN_SCOPES,
        "state": state,
    }

    # Build auth URL
    query = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
    auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{query}"

    resp = RedirectResponse(auth_url)
    resp.set_cookie(
        LI_STATE_COOKIE,
        state,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=600,
    )
    return resp


@app.get("/api/linkedin/callback")
def linkedin_callback(code: str = "", state: str = "", request: Request = None):
    _require_linkedin_oauth_config()
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth `code`")

    if request is None:
        raise HTTPException(status_code=400, detail="Missing request context")

    expected_state = request.cookies.get(LI_STATE_COOKIE, "")
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    secure_cookie = request.url.scheme == "https"

    # Exchange code -> access token
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LINKEDIN_REDIRECT_URI,
        "client_id": LINKEDIN_CLIENT_ID,
        "client_secret": LINKEDIN_CLIENT_SECRET,
    }

    try:
        token_res = requests.post(token_url, data=data, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {e}")

    if not token_res.ok:
        raise HTTPException(status_code=token_res.status_code, detail=token_res.text[:2000])

    payload = token_res.json()
    access_token = (payload.get("access_token") or "").strip()
    expires_in = int(payload.get("expires_in") or 0)
    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in OAuth response")

    resp = RedirectResponse(url="/")
    # Store token in an HttpOnly cookie (frontend JS cannot read it).
    cookie_kwargs = {
        "httponly": True,
        "secure": secure_cookie,
        "samesite": "lax",
    }
    if expires_in:
        cookie_kwargs["max_age"] = max(0, expires_in - 60)
    resp.set_cookie(LI_COOKIE_NAME, access_token, **cookie_kwargs)
    # Clear state cookie
    resp.delete_cookie(LI_STATE_COOKIE)
    return resp


@app.post("/api/linkedin/disconnect")
def linkedin_disconnect(request: Request):
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(LI_COOKIE_NAME)
    resp.delete_cookie(LI_STATE_COOKIE)
    return resp

