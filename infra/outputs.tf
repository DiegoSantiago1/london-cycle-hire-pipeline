# Valores que o GitHub Actions precisa (gravados como variáveis do repositório, não segredos:
# nenhum deles dá acesso sozinho; o acesso depende do token OIDC do próprio GitHub).

output "bucket_bruto" {
  description = "Bucket do bruto ao vivo (variável BRUTO_BUCKET do repositório)."
  value       = aws_s3_bucket.bruto.id
}

output "papel_github_leitura" {
  description = "Papel que o GitHub Actions assume pelo OIDC (variável AWS_ROLE_ARN)."
  value       = aws_iam_role.github_leitura.arn
}

output "lambda_coleta" {
  description = "Nome da função de coleta."
  value       = aws_lambda_function.coleta.function_name
}

output "agendamento" {
  description = "Nome do agendamento no EventBridge Scheduler."
  value       = aws_scheduler_schedule.coleta.name
}

output "regiao" {
  value = var.regiao
}
