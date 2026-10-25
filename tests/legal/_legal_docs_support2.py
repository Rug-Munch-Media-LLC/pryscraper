from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pry.api.routers.data.legal_docs import router as legal_router
from pry.core.errors import PryError


def _recap_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": 77,
                "caseName": "In re Example Corp.",
                "docketNumber": "3:23-bk-00099",
                "court": "ca9",
                "dateFiled": "2023-04-01",
                "natureOfSuit": "Bankruptcy",
                "source": "RECAP",
                "absoluteURL": "https://www.courtlistener.com/docket/77/example/",
            }
        ],
    }

def _justia_search_html() -> str:
    return """<html><body>
<div class="case-block">
  <h2><a href="/docket/new-york-southern-district-court/example-1">SEC v. Example Corp.</a></h2>
  <div class="meta">1:22-cv-00001 &middot; Southern District of New York &middot; filed 2022-01-15</div>
</div>
<div class="case-block">
  <h2><a href="/docket/texas-southern-district-court/example-2">Doe v. Fictitious LLC</a></h2>
  <div class="meta">4:21-cv-00420 &middot; Southern District of Texas &middot; filed 2021-06-30</div>
</div>
</body></html>"""

def _pacer_payload() -> dict[str, Any]:
    return {
        "id": 999,
        "case_name": "In re PACER Corp.",
        "docket_number": "1:24-bk-00099",
        "court": "nyb",
        "date_filed": "2024-05-01",
        "date_terminated": None,
        "nature_of_suit": "Bankruptcy",
        "cause": None,
        "description": "PACER-fetched bankruptcy docket",
        "jury_demand": "None",
        "jurisdiction_type": "Federal Question",
        "date_argued": None,
        "date_reargued": None,
        "date_last_filing": None,
        "appeal_from": None,
        "panel": None,
    }

def _ny_ecourts_html() -> str:
    return """<html><body><table>
<tr class="data">
  <td>651256/2023</td><td>Contract</td><td>11/08/2023</td>
  <td>&nbsp;</td><td>ACME CORP</td><td>EXAMPLE LLC</td>
</tr>
<tr class="data">
  <td>650001/2022</td><td>Tort</td><td>02/14/2022</td>
  <td>HON JUDGE</td><td>JANE DOE</td><td>GLOBEX INC</td>
</tr>
</table></body></html>"""

@pytest.fixture
def legal_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(legal_router)
    return app

def _client(app: FastAPI) -> TestClient:
    return TestClient(app)
