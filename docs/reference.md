# API reference

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MECHLENS_API_KEY` | none | Workspace API key. Required unless passed as `api_key`. |
| `MECHLENS_API_URL` | `https://mechlens-cloud-fgstc.ondigitalocean.app` | The MechLens Cloud deployment to upload to. |
| `MECHLENS_DIR` | `.mechlens/runs` | Where finished runs are saved as JSON. |

Arguments passed to [`start_run`][mechlens.start_run] override these.

## Recording runs

::: mechlens.start_run

::: mechlens.Run
    options:
      members: [log_example, log_metrics, finish, retry_upload]

::: mechlens.UploadReceipt

## Errors

::: mechlens.MechLensError

::: mechlens.MechLensConfigurationError

::: mechlens.MechLensUploadError

## Advanced

::: mechlens.CloudClient
