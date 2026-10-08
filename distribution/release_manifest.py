"""Sign installer metadata locally; only the public verification key is published."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def initialize(path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from toolbox_manager.pptagent import _secret
    from distribution.install_local import no_reparse
    path=no_reparse(path)
    if path.is_relative_to(ROOT):raise ValueError('Signing keys must remain outside the source repository')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        key=Ed25519PrivateKey.from_private_bytes(_secret(path.read_bytes(),decrypt=True))
    else:
        key=Ed25519PrivateKey.generate()
        with path.open('xb') as stream:
            stream.write(_secret(key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())))
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    identifier='ed25519-'+hashlib.sha256(public).hexdigest()[:16]
    cfgpath=ROOT/'distribution/release_config.json'
    cfg=json.loads(cfgpath.read_text('utf-8'))
    cfg['trusted_keys'][identifier]=base64.b64encode(public).decode()
    cfgpath.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    return {'key_id':identifier,'private_key_protection':'Windows DPAPI current user','public_config':str(cfgpath)}


def sign(installer,keypath,notes,output):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from toolbox_manager.pptagent import _secret
    from scripts.release_info import check_release
    from toolbox_manager.software_updates import verified_manifest
    release=check_release(ROOT)
    cfg=json.loads((ROOT/'distribution/release_config.json').read_text('utf-8'))
    if installer.name!=f'PPTToolbox-{release["version"]}-Setup.exe':raise ValueError('Installer filename differs from release version')
    key=Ed25519PrivateKey.from_private_bytes(_secret(Path(keypath).read_bytes(),decrypt=True))
    public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    identifier=next((k for k,v in cfg['trusted_keys'].items() if v==public),None)
    if not identifier:raise ValueError('Signing key is not trusted by this source release')
    with installer.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    manifest={**release,'format':'ppttoolbox-update/1','repository':cfg['repository'],
              'tag':'v'+release['version'],'platform':'windows-x64','updater_version':1,
              'database_schema':{'minimum':1,'maximum':1},'published_at':datetime.now(timezone.utc).isoformat(),
              'notes':Path(notes).read_text('utf-8'),
              'asset':{'name':installer.name,'size':installer.stat().st_size,'sha256':checksum,
                       'url':f'https://github.com/{cfg["repository"]}/releases/download/v{release["version"]}/{installer.name}'}}
    raw=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    signature=(json.dumps({'key_id':identifier,'signature':base64.b64encode(key.sign(raw)).decode()},indent=2)+'\n').encode()
    verified_manifest(raw,signature,cfg)
    output.mkdir(parents=True,exist_ok=True)
    for name,data in [(cfg['manifest'],raw),(cfg['signature'],signature)]:
        with (output/name).open('xb') as stream:stream.write(data)
    (output/'SHA256SUMS.txt').write_text(f'{checksum}  {installer.name}\n'+''.join(
        hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in [(cfg['manifest'],raw),(cfg['signature'],signature)]),encoding='utf-8')
    return {'version':release['version'],'sha256':checksum,'output':str(output),'key_id':identifier}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init-key');init.add_argument('--private-key',type=Path,required=True)
    signing=sub.add_parser('sign')
    for name in ('installer','private-key','notes','output'):signing.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(initialize(args.private_key) if args.command=='init-key' else
                     sign(args.installer,args.private_key,args.notes,args.output),indent=2))
