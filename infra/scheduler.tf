# EventBridge Scheduler: dispara a Lambda nos mesmos minutos que o cron do GitHub usava
# (7, 22, 37, 52 UTC; D13). Sem janela flexível: na hora certa, que é o que se mede.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    # Só agendamentos desta conta podem usar o papel (proteção contra "confused deputy").
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.conta]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.nome_lambda}-scheduler"
  description        = "Papel do EventBridge Scheduler: só invocar a Lambda de coleta."
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.coleta.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invocar-coleta"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "coleta" {
  name        = "${local.nome_lambda}-15min"
  description = "Coleta da API BikePoint a cada 15 minutos (minutos 7, 22, 37 e 52 UTC)."

  schedule_expression          = "cron(7,22,37,52 * * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.coleta.arn
    role_arn = aws_iam_role.scheduler.arn
    # O registro da execução grava evento = "eventbridge_scheduler": conta como agendada.
    input = jsonencode({ gatilho = "eventbridge_scheduler" })

    # Nova tentativa só se a invocação nem chegou a acontecer (ex.: limite de concorrência),
    # e no máximo 5 min depois: um retrato atrasado demais já seria da janela seguinte.
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 300
    }
  }
}
