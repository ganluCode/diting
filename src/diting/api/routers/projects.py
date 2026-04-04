"""项目管理路由"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Page, paginate

from diting.api.deps import get_project_service, get_scan_service
from diting.core.models import EnhanceRequest, Project, ProjectCreate, ProjectUpdate, ScanRequest
from diting.core.services.project import ProjectService
from diting.core.services.scan import ScanService

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=Page[Project])
async def list_projects(
    projects: Annotated[ProjectService, Depends(get_project_service)],
):
    items = await projects.list_all()
    return paginate(items)


@router.post("", response_model=Project, status_code=201)
async def create_project(
    req: ProjectCreate,
    projects: Annotated[ProjectService, Depends(get_project_service)],
):
    try:
        return await projects.create(req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
):
    project = await projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


@router.put("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    projects: Annotated[ProjectService, Depends(get_project_service)],
):
    project = await projects.update(project_id, req)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
):
    project = await projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    await projects.delete(project_id)


@router.post("/{project_id}/scan")
async def scan_project(
    project_id: str,
    req: ScanRequest,
    scanner: Annotated[ScanService, Depends(get_scan_service)],
):
    try:
        result = await scanner.scan(
            project_id,
            reset=req.reset,
            skip_enhance=req.skip_enhance,
        )
        return {
            "ok": result.ok,
            "project_id": result.project_id,
            "files_scanned": result.files_scanned,
            "nodes_written": result.nodes_written,
            "details": result.details,
            "errors": result.errors,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/enhance")
async def enhance_project(
    project_id: str,
    req: EnhanceRequest,
    scanner: Annotated[ScanService, Depends(get_scan_service)],
):
    try:
        result = await scanner.enhance(
            project_id, clean=req.clean, verify=req.verify
        )
        return {
            "ok": result.ok,
            "summary": result.summary(),
            "verify_warnings": result.verify_warnings,
            "steps": [
                {"file": s.file, "description": s.description,
                 "count": s.count, "error": s.error}
                for s in result.steps
            ],
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
