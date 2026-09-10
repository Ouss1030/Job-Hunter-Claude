"""
JOBHUNTER - GENERIC PUBLIC ATS ENGINES V1

Reusable read-only clients for public job-board endpoints.
Adding an employer later becomes configuration instead of a new scraper.
"""

from __future__ import annotations
import requests

TIMEOUT=30
HEADERS={"User-Agent":"JobHunter/9.0 personal job search","Accept":"application/json"}

def _get_json(url,params=None):
    r=requests.get(url,params=params,headers=HEADERS,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def greenhouse(board_token:str):
    return _get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        {"content":"true"},
    )

def lever(company:str):
    return _get_json(
        f"https://api.lever.co/v0/postings/{company}",
        {"mode":"json"},
    )

def recruitee(company:str):
    return _get_json(f"https://{company}.recruitee.com/api/offers/")

def ashby(board_name:str):
    return _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board_name}")

def smartrecruiters(company:str,limit:int=100,offset:int=0):
    return _get_json(
        f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
        {"limit":limit,"offset":offset},
    )
