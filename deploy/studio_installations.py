#!/usr/bin/env python3
"""Owner-only installation list/attach CLI; credentials never appear in output."""
import argparse
import json
from pathlib import Path
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
import uuid
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):raise ValueError('Authenticated redirect refused')

def request(method,path,body=None):
    token=(Path.home()/'.local/share/dots/mobile-token').read_text().strip()
    req=Request('https://dots.kosmos.institute/v1'+path,method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=15) as response:return json.load(response)

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    s.add_parser('list');a=s.add_parser('attach');a.add_argument('installation_id');a.add_argument('crew_member_id')
    args=p.parse_args()
    result=request('GET','/hosted/installations') if args.action=='list' else request('POST','/hosted/installations/'+str(uuid.UUID(args.installation_id))+'/attach',{'crew_member_id':args.crew_member_id})
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
