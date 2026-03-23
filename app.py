from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

app = FastAPI()


@app.get("/")
def root():
    # Serve the existing frontend UI from the repo root.
    index_path = Path(__file__).resolve().parent / "index.html"
    return FileResponse(str(index_path))


class LinkedInPostRequest(BaseModel):
    access_token: str
    text: str


@app.post("/api/linkedin/post")
def post_to_linkedin(req: LinkedInPostRequest):
    """
    Server-side LinkedIn posting.
    This avoids browser CORS issues and keeps tokens out of JS fetches to LinkedIn.
    """
    token = (req.access_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing access_token")

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

