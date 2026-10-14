variable "regiao" {
  description = "Região da AWS. Londres: perto da API da TfL e dos dados."
  type        = string
  default     = "eu-west-2"
}

variable "projeto" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
  default     = "london-cycle-hire"
}

variable "repositorio_github" {
  description = "Repositório (dono/nome) que pode assumir o papel de leitura pelo OIDC."
  type        = string
  default     = "DiegoSantiago1/london-cycle-hire-pipeline"
}

variable "email_alertas" {
  description = "E-mail que recebe os alarmes da coleta. Vazio = sem assinatura por e-mail."
  type        = string
  default     = ""
  # Fica em terraform.tfvars, fora do git (o repositório é público).
}

variable "retencao_logs_dias" {
  description = "Por quantos dias o CloudWatch guarda os logs da Lambda."
  type        = number
  default     = 14
}
