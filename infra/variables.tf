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

# IDs imutáveis (gh api repos/<dono>/<repo> --jq '.owner.id, .id'): o GitHub os inclui no
# "sub" do token OIDC, e a condição do papel compara com eles.
variable "github_id_dono" {
  description = "ID numérico do dono do repositório no GitHub."
  type        = string
  default     = "263783753"
}

variable "github_id_repositorio" {
  description = "ID numérico do repositório no GitHub."
  type        = string
  default     = "1403573171"
}

variable "email_alertas" {
  description = "E-mail que recebe os alarmes da coleta. Vazio = sem assinatura por e-mail."
  type        = string
  default     = ""
  # Fica em terraform.tfvars, fora do git (o repositório é público).
}

variable "athena_inicio_bruto" {
  description = "Primeiro dia (UTC) com retratos no S3: início da projeção de partições do Athena."
  type        = string
  default     = "2026-10-14"
}

variable "athena_limite_bytes" {
  description = "Trava de custo: nenhuma consulta do Athena pode ler mais que isto (1 GB = US$ 0,005)."
  type        = number
  default     = 1073741824
}

variable "retencao_logs_dias" {
  description = "Por quantos dias o CloudWatch guarda os logs da Lambda."
  type        = number
  default     = 14
}
