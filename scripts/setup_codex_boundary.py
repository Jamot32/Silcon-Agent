#!/usr/bin/env python3
"""Install one explicit external Codex host-policy generation."""
import argparse,json,sys
from app.llm.host_policy import install,HostSetupError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',required=True);parser.add_argument('--generation',required=True)
    args=parser.parse_args()
    try:
        result=install(args.inventory,args.generation)
        print(json.dumps({'status':'installed','policy':str(result),'continuous_isolation_proved':False}))
        return 0
    except HostSetupError:
        print('Codex host inventory/policy setup rejected.',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
