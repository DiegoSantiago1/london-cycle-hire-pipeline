# Infrastructure (AWS + Terraform)

The live collector runs on AWS. Everything here is created and destroyed by Terraform; nothing was clicked in the console. Decisions D45–D49 in [docs/DECISOES.md](../docs/DECISOES.md).

```
EventBridge Scheduler ── cron(7,22,37,52 * * * ? *) UTC, no flexible window
   └─► Lambda london-cycle-hire-coleta   (src/bicicletas/coleta_api.py, Python 3.14, arm64, 256 MB)
         └─► S3 london-cycle-hire-bruto-<account>/bruto/<source>/data=YYYY-MM-DD/...
               ▲ read-only, prefix bruto/ only
GitHub Actions ──OIDC (token → 1 h credentials, repo + main branch only)──┘
CloudWatch: Lambda logs (14 days) · alarm "failing" (≥2 errors/hour) · alarm "stopped" (<3 runs/hour, 2 hours) ─► SNS e-mail
```

| File | What it creates |
|---|---|
| `s3.tf` | Raw-data bucket: public access blocked, owner-enforced (no ACLs), versioned, SSE-S3, TLS-only policy, old versions expire after 30 days |
| `lambda.tf` | The function (zip with only `bicicletas/__init__.py` and `coleta_api.py`), its log group, and a role that can only `PutObject` into the two raw prefixes and write its own logs. Async retries off: a retry would write a second snapshot with a different time |
| `scheduler.tf` | The schedule and a role that can only invoke this function (`aws:SourceAccount` condition). The event `{"gatilho": "eventbridge_scheduler"}` marks the run as scheduled in the run record |
| `github_oidc.tf` | GitHub's OIDC provider and the read-only role for the daily jobs |
| `monitoring.tf` | SNS topic, e-mail subscription (must be confirmed by clicking the link AWS sends) and the two alarms |

## How the raw data stays immutable

1. The Lambda writes with `If-None-Match: *`: S3 itself refuses to replace an existing key (tested: `PreconditionFailed`, object unchanged).
2. The Lambda's role has `s3:PutObject` only: no read, list or delete.
3. The bucket is versioned: even a human mistake leaves the previous version for 30 days.
4. Every day is mirrored to a public GitHub Release (`.github/workflows/pacote.yml`), so the data also exists outside AWS.

## Cost

Nothing billed per hour (no server, managed database or NAT gateway). Usage is about 2,900 Lambda runs, ~6,000 S3 writes and ~230 MB of new data a month. The account is on the AWS Free plan (credits until 13 Apr 2027) with a budget alert from the first cent; real cost will be read from Cost Explorer after the first full month, not estimated here.

## Run it

Needs Docker and an AWS session from `aws login` (temporary credentials, no access keys).

```bash
bash infra/tf.sh init
bash infra/tf.sh plan -out=plano.tfplan     # read it before applying
bash infra/tf.sh apply plano.tfplan
bash infra/tf.sh output                      # values for the repo variables below
```

`tf.sh` runs the official `hashicorp/terraform` image because, on the author's machine, an antivirus intercepts even the local connection between Terraform and the AWS provider. On any other machine, plain `terraform` in this folder works the same.

GitHub repository variables (not secrets: none of them grants access alone): `AWS_ROLE_ARN`, `AWS_REGION`, `BRUTO_BUCKET`. Without them, the workflows skip the AWS steps and use only the releases.

Local-only files (in `.gitignore`): `terraform.tfstate`, `terraform.tfvars` (alert e-mail), `.terraform/`, `.build/`.

## Turning it off

`bash infra/tf.sh destroy` removes everything except a bucket that still has objects (Terraform refuses on purpose). To keep the data, run `aws s3 sync s3://<bucket>/bruto ./bruto` first; it is also in the public releases.

---

**Em português:** a coleta roda na AWS (EventBridge Scheduler → Lambda → S3), tudo criado pelo Terraform. O bruto é imutável por quatro camadas (gravação com `If-None-Match`, papel só com `PutObject`, versionamento e espelho nas releases do GitHub). O GitHub Actions lê o S3 pelo OIDC, sem chave guardada. Nada cobra por hora; o custo real será lido no Cost Explorer depois do primeiro mês. Para aplicar: `bash infra/tf.sh init`, `plan -out=plano.tfplan` e `apply plano.tfplan`, com o Docker aberto e uma sessão do `aws login`.
