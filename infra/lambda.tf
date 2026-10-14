# A coleta na Lambda: o mesmo coleta_api.py que roda no GitHub Actions, sem dependências
# (o boto3 do destino S3 já vem no runtime). O pacote tem só os dois arquivos que ela usa.

data "archive_file" "coleta" {
  type        = "zip"
  output_path = "${path.module}/.build/coleta.zip"

  source {
    content  = file("${path.module}/../src/bicicletas/__init__.py")
    filename = "bicicletas/__init__.py"
  }
  source {
    content  = file("${path.module}/../src/bicicletas/coleta_api.py")
    filename = "bicicletas/coleta_api.py"
  }
}

# Criado antes da função para a retenção valer desde o primeiro log (sem isso a Lambda
# cria o grupo sozinha, com retenção infinita).
resource "aws_cloudwatch_log_group" "coleta" {
  name              = "/aws/lambda/${local.nome_lambda}"
  retention_in_days = var.retencao_logs_dias
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "coleta" {
  name               = "${local.nome_lambda}-lambda"
  description        = "Papel da Lambda de coleta: grava no bruto e escreve os próprios logs."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Menor privilégio (D47): só gravar nas duas pastas do bruto e nos próprios logs.
# Sem GetObject, DeleteObject ou ListBucket: a coleta não lê nem apaga nada.
data "aws_iam_policy_document" "coleta" {
  statement {
    sid     = "GravarBruto"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.bruto.arn}/bruto/bikepoint/*",
      "${aws_s3_bucket.bruto.arn}/bruto/execucoes_coleta/*",
    ]
  }
  statement {
    sid       = "EscreverLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.coleta.arn}:*"]
  }
}

resource "aws_iam_role_policy" "coleta" {
  name   = "gravar-bruto-e-logs"
  role   = aws_iam_role.coleta.id
  policy = data.aws_iam_policy_document.coleta.json
}

resource "aws_lambda_function" "coleta" {
  function_name    = local.nome_lambda
  description      = "Coleta um retrato da API BikePoint da TfL e grava intocado no S3."
  role             = aws_iam_role.coleta.arn
  filename         = data.archive_file.coleta.output_path
  source_code_hash = data.archive_file.coleta.output_base64sha256
  handler          = "bicicletas.coleta_api.lambda_handler"
  runtime          = "python3.14"
  architectures    = ["arm64"] # Graviton: mais barato por segundo que x86
  memory_size      = 256
  # 3 tentativas de 30 s + esperas de 5 s e 10 s = 105 s no pior caso.
  timeout = 150

  environment {
    variables = {
      BICICLETAS_BUCKET_BRUTO = aws_s3_bucket.bruto.id
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.coleta.name
  }

  depends_on = [aws_iam_role_policy.coleta]
}

# A função já tenta 3 vezes por dentro. Uma nova tentativa da Lambda gravaria um segundo
# retrato com outro horário: melhor falhar, registrar e esperar a próxima janela.
resource "aws_lambda_function_event_invoke_config" "coleta" {
  function_name                = aws_lambda_function.coleta.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 300
}
