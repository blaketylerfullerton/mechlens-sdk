# API reference

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MECHLENS_API_KEY` | none | Workspace API key. Required unless passed as `api_key`. |
| `MECHLENS_API_URL` | `https://mechlens.dev` | The MechLens Cloud deployment to upload to. |
| `MECHLENS_DIR` | `.mechlens/runs` | Where finished runs are saved as JSON. |

Arguments passed to [`experiment`][mechlens.experiment] or
[`start_run`][mechlens.start_run] override these.

## Declaring an experiment

::: mechlens.experiment

::: mechlens.Experiment
    options:
      members: [reference, intervention, control, baseline, url]

::: mechlens.Paper

::: mechlens.Correction

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

::: mechlens.MechLensWarning

## Advanced

::: mechlens.CloudClient
