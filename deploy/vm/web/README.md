# Deploy the public web app

Use [DEPLOYMENT.md](DEPLOYMENT.md) for the complete VM bootstrap, fixed
production configuration, Nginx/HTTPS, Tailscale CI, GitHub settings,
release deployment, developer workflow, logs, rollback and database recovery.

The prepared setup uses `/srv/aivideo/releases/<commit>` and persistent
`shared/runtime`, runs Django and one queue worker under a dedicated account,
and leaves the existing private MCP/OpenRouter/RunPod services in place.

After completing the runbook setup, deploy a reviewed main commit on the VM:

```bash
sudo -u aivideo-deploy -H bash /usr/local/lib/aivideo/deploy-release.sh FULL_MAIN_SHA
```

No production environment file or test file was created by this preparation.
