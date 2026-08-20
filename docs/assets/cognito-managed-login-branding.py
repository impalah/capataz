#!/usr/bin/env python3
"""Apply Capataz's theme to a Cognito Managed Login branding style.

Palette source of truth: frontend/src/styles/app.scss (:root = dark theme,
body.body--light = light theme) — the same tokens used for
docs/assets/authentik-custom.css, so Authentik and Cognito stay visually
consistent. Requires Managed Login v2 (check with `aws cognito-idp
describe-user-pool-domain --domain <domain>` -> "ManagedLoginVersion": 2);
the classic Hosted UI doesn't have this API.

Requires only the AWS CLI (configured with credentials that can call
cognito-idp:DescribeManagedLoginBrandingByClient / UpdateManagedLoginBranding)
and Python 3 stdlib — no boto3, no repo venv.

Usage:
    python3 docs/assets/cognito-managed-login-branding.py \\
        --user-pool-id eu-west-1_XXXXXXXXX \\
        --client-id <app_client_id> \\
        --region eu-west-1 \\
        --apply              # omit --apply to just print the payload (dry run)

Needs an existing Managed Login Branding resource for the client (Cognito
creates one automatically the first time you open the domain's Branding
Designer, or the first time any style is applied) — the script looks it up
via describe-managed-login-branding-by-client, it does not create one.
"""

import argparse
import base64
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FAVICON_SVG = REPO_ROOT / "frontend" / "public" / "favicon.svg"

DARK = dict(
    bg="101618ff", surface="182023ff", surface2="1d282cff", border="344245ff",
    text="e7ecebff", text_muted="aab7b8ff", primary="64aab0ff",
    error="e18080ff", success="8ac47dff", brand="ff6600ff",
)
LIGHT = dict(
    bg="f4f6f6ff", surface="ffffffff", surface2="eef1f1ff", border="d7dfe0ff",
    text="16211fff", text_muted="55676aff", primary="2f7d84ff",
    error="b3261eff", success="1f6b3aff", brand="ff6600ff",
)
WHITE = "ffffffff"
WARNING = "d69a45ff"  # Quasar $warning (frontend/src/styles/quasar-variables.sass) — same both modes

AWS_ENV = {**os.environ, "AWS_PAGER": ""}


def aws_json(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--no-cli-pager", "--output", "json"],
        capture_output=True, text=True, check=True, env=AWS_ENV,
    )
    return json.loads(result.stdout)


def sanitized_favicon_b64() -> str:
    # Cognito's SVG sanitizer rejects role/aria-label on the root <svg> element.
    # Strip them for the uploaded copy only; frontend/public/favicon.svg keeps them.
    svg = FAVICON_SVG.read_text()
    svg = svg.replace(' role="img" aria-label="Capataz"', "")
    return base64.b64encode(svg.encode()).decode()


def build_settings(default_settings: dict) -> dict:
    settings = copy.deepcopy(default_settings)
    c = settings["components"]
    cc = settings["componentClasses"]
    cat = settings["categories"]

    cat["global"]["colorSchemeMode"] = "DYNAMIC"
    cat["global"]["pageHeader"]["enabled"] = True
    cat["global"]["pageFooter"]["enabled"] = True
    # displayGraphics turns on AWS's decorative triangle/gradient motif behind the form —
    # unrelated to components.form.logo. Keep it off or it overrides pageBackground.color.
    cat["form"]["displayGraphics"] = False

    c["pageBackground"]["image"]["enabled"] = False
    c["pageBackground"]["lightMode"]["color"] = LIGHT["bg"]
    c["pageBackground"]["darkMode"]["color"] = DARK["bg"]

    c["form"]["lightMode"]["backgroundColor"] = LIGHT["surface"]
    c["form"]["lightMode"]["borderColor"] = LIGHT["border"]
    c["form"]["darkMode"]["backgroundColor"] = DARK["surface"]
    c["form"]["darkMode"]["borderColor"] = DARK["border"]
    c["form"]["borderRadius"] = 12.0  # --radius-lg
    c["form"]["logo"] = {"location": "CENTER", "position": "TOP", "enabled": True, "formInclusion": "IN"}

    for key in ("pageHeader", "pageFooter"):
        c[key]["lightMode"]["borderColor"] = LIGHT["border"]
        c[key]["lightMode"]["background"]["color"] = LIGHT["surface"]
        c[key]["darkMode"]["borderColor"] = DARK["border"]
        c[key]["darkMode"]["background"]["color"] = DARK["surface"]
    c["pageHeader"]["logo"] = {"location": "START", "enabled": True}
    c["pageFooter"]["logo"] = {"location": "START", "enabled": False}

    # Primary action: teal default, brand-orange hover/active — same convention as
    # docs/assets/authentik-custom.css's .pf-c-button.pf-m-primary override.
    for mode, colors in (("lightMode", LIGHT), ("darkMode", DARK)):
        c["primaryButton"][mode]["defaults"] = {"backgroundColor": colors["primary"], "textColor": WHITE}
        c["primaryButton"][mode]["hover"] = {"backgroundColor": colors["brand"], "textColor": WHITE}
        c["primaryButton"][mode]["active"] = {"backgroundColor": colors["brand"], "textColor": WHITE}

        c["secondaryButton"][mode]["defaults"] = {"backgroundColor": colors["surface"], "borderColor": colors["primary"], "textColor": colors["primary"]}
        c["secondaryButton"][mode]["hover"] = {"backgroundColor": colors["surface2"], "borderColor": colors["brand"], "textColor": colors["brand"]}
        c["secondaryButton"][mode]["active"] = c["secondaryButton"][mode]["hover"]

        c["idpButton"]["standard"][mode]["defaults"] = {"backgroundColor": colors["surface"], "borderColor": colors["border"], "textColor": colors["text"]}
        c["idpButton"]["standard"][mode]["hover"] = {"backgroundColor": colors["surface2"], "borderColor": colors["primary"], "textColor": colors["primary"]}
        c["idpButton"]["standard"][mode]["active"] = c["idpButton"]["standard"][mode]["hover"]

        cc["input"][mode]["defaults"] = {"backgroundColor": colors["surface2"] if mode == "darkMode" else colors["surface"], "borderColor": colors["border"]}
        cc["input"][mode]["placeholderColor"] = colors["text_muted"]
        cc["inputDescription"][mode]["textColor"] = colors["text_muted"]

        cc["dropDown"][mode]["defaults"]["itemBackgroundColor"] = colors["surface"]
        cc["dropDown"][mode]["hover"] = {"itemBackgroundColor": colors["surface2"], "itemBorderColor": colors["primary"], "itemTextColor": colors["text"]}
        cc["dropDown"][mode]["match"] = {"itemBackgroundColor": colors["surface2"], "itemTextColor": colors["primary"]}

        cc["optionControls"][mode]["defaults"] = {"backgroundColor": colors["surface"], "borderColor": colors["border"]}
        cc["optionControls"][mode]["selected"] = {"backgroundColor": colors["primary"], "foregroundColor": WHITE}

        cc["divider"][mode]["borderColor"] = colors["border"]

        c["pageText"][mode] = {"bodyColor": colors["text_muted"], "headingColor": colors["text"], "descriptionColor": colors["text_muted"]}

    c["favicon"]["enabledTypes"] = ["SVG"]  # only an SVG asset is uploaded below

    c["alert"]["lightMode"]["error"] = {"backgroundColor": "fbe9e9ff", "borderColor": LIGHT["error"]}
    c["alert"]["darkMode"]["error"] = {"backgroundColor": "2a1414ff", "borderColor": DARK["error"]}

    cc["statusIndicator"]["lightMode"]["success"] = {"backgroundColor": "eef7edff", "borderColor": LIGHT["success"], "indicatorColor": LIGHT["success"]}
    cc["statusIndicator"]["lightMode"]["error"] = {"backgroundColor": "fbe9e9ff", "borderColor": LIGHT["error"], "indicatorColor": LIGHT["error"]}
    cc["statusIndicator"]["lightMode"]["warning"] = {"backgroundColor": "fbf1e4ff", "borderColor": WARNING, "indicatorColor": WARNING}
    cc["statusIndicator"]["darkMode"]["success"] = {"backgroundColor": "17241aff", "borderColor": DARK["success"], "indicatorColor": DARK["success"]}
    cc["statusIndicator"]["darkMode"]["error"] = {"backgroundColor": "2a1414ff", "borderColor": DARK["error"], "indicatorColor": DARK["error"]}
    cc["statusIndicator"]["darkMode"]["warning"] = {"backgroundColor": "2a2013ff", "borderColor": WARNING, "indicatorColor": WARNING}

    cc["buttons"]["borderRadius"] = 6.0  # --radius-sm

    return settings


def build_assets() -> list[dict]:
    svg_b64 = sanitized_favicon_b64()
    return [
        {"Category": category, "ColorMode": color_mode, "Extension": "SVG", "Bytes": svg_b64}
        for category in ("FORM_LOGO", "PAGE_HEADER_LOGO", "FAVICON_SVG")
        for color_mode in ("LIGHT", "DARK")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-pool-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--apply", action="store_true", help="Actually call update-managed-login-branding (default: dry run, prints the payload)")
    args = parser.parse_args()

    branding = aws_json(
        "cognito-idp", "describe-managed-login-branding-by-client",
        "--user-pool-id", args.user_pool_id, "--client-id", args.client_id, "--region", args.region,
    )["ManagedLoginBranding"]

    payload = {
        "UserPoolId": args.user_pool_id,
        "ManagedLoginBrandingId": branding["ManagedLoginBrandingId"],
        "UseCognitoProvidedValues": False,
        "Settings": build_settings(branding["Settings"]),
        "Assets": build_assets(),
    }

    if not args.apply:
        print(json.dumps(payload, indent=2))
        print(f"\n# dry run — {len(json.dumps(payload))} bytes (2MB limit). Re-run with --apply to push this.", file=sys.stderr)
        return

    tmp = Path("/tmp") / f"cognito-branding-{args.client_id}.json"
    tmp.write_text(json.dumps(payload))
    subprocess.run(
        ["aws", "cognito-idp", "update-managed-login-branding", "--cli-input-json", f"file://{tmp}",
         "--region", args.region, "--no-cli-pager"],
        check=True, capture_output=True, text=True, env=AWS_ENV,
    )
    tmp.unlink()
    print("Applied.")


if __name__ == "__main__":
    main()
