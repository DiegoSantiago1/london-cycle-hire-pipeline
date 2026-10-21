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

output "athena_grupo" {
  description = "Grupo de trabalho do Athena (com limite de bytes por consulta)."
  value       = aws_athena_workgroup.consultas.name
}

output "glue_banco" {
  description = "Banco do Glue Data Catalog com a tabela dos retratos."
  value       = aws_glue_catalog_database.bicicletas.name
}

output "regiao" {
  value = var.regiao
}
