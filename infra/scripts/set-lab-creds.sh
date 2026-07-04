#!/usr/bin/env bash
# Load AWS Academy Learner Lab LabRole credentials into the current shell so
# `terraform` and `aws` pick them up via the standard env-var credential chain.
#
# Usage (must be SOURCED, not executed, so the exports land in your shell):
#   source infra/scripts/set-lab-creds.sh
#
# Get fresh values each session from the Learner Lab UI: "AWS Details" ->
# "AWS CLI" (click "Show"). Credentials are session-scoped and expire when the
# lab session ends — re-source this whenever terraform/aws starts failing auth.
#
# Nothing here is written to disk: the values only ever exist as env vars in
# this shell, which matches the lab's own rotate-every-session model.

if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
  echo "This script must be sourced, not executed:" >&2
  echo "  source ${BASH_SOURCE[0]:-set-lab-creds.sh}" >&2
  exit 1
fi

read -r -p "AWS Access Key ID: " _cw_access_key_id
read -r -s -p "AWS Secret Access Key: " _cw_secret_access_key
echo
read -r -s -p "AWS Session Token: " _cw_session_token
echo

export AWS_ACCESS_KEY_ID="${_cw_access_key_id}"
export AWS_SECRET_ACCESS_KEY="${_cw_secret_access_key}"
export AWS_SESSION_TOKEN="${_cw_session_token}"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_REGION="us-east-1"

unset _cw_access_key_id _cw_secret_access_key _cw_session_token

echo "Credentials exported for this shell. Verifying identity..."
aws sts get-caller-identity
