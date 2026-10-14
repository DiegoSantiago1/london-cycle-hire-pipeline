# Alarmes (D49): quem descobre que a coleta parou é o alarme, não a página do dia seguinte.

resource "aws_sns_topic" "alertas" {
  name = "${var.projeto}-alertas"
}

# A assinatura por e-mail fica "pendente" até o dono clicar no link de confirmação.
resource "aws_sns_topic_subscription" "email" {
  count     = var.email_alertas == "" ? 0 : 1
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.email_alertas
}

# Falhas: uma falha isolada (a API da TfL piscou) é registrada e não acorda ninguém.
# Duas ou mais na mesma hora já é problema.
resource "aws_cloudwatch_metric_alarm" "coleta_falhando" {
  alarm_name          = "${local.nome_lambda}-falhando"
  alarm_description   = "A Lambda de coleta falhou 2 vezes ou mais na última hora. Veja os logs em ${aws_cloudwatch_log_group.coleta.name}."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.coleta.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]
}

# Coleta parada: são 4 execuções por hora. Menos de 3 em duas horas seguidas = o
# agendador parou ou a função foi desligada. Sem dado nenhum também conta como parada.
resource "aws_cloudwatch_metric_alarm" "coleta_parada" {
  alarm_name          = "${local.nome_lambda}-parada"
  alarm_description   = "A Lambda de coleta rodou menos de 3 vezes por hora em 2 horas seguidas (o esperado é 4)."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.coleta.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 3
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]
}
