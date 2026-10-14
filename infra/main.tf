# Infraestrutura da coleta ao vivo na AWS (fase 7, docs/DECISOES.md D45 a D49):
#
#   EventBridge Scheduler (minutos 7, 22, 37, 52 UTC)
#     └─► Lambda coleta (src/bicicletas/coleta_api.py, Python 3.14, sem dependências)
#           └─► S3: bruto intocado, mesmas chaves de antes (bruto/<fonte>/data=AAAA-MM-DD/)
#   GitHub Actions ──OIDC──► papel só de leitura no bruto (sem chave guardada)
#   CloudWatch: logs da Lambda e alarmes (falha e coleta parada) ──► e-mail (SNS)
#
# Nada aqui cobra por hora (sem servidor, banco ou NAT): o custo é por uso.

provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      projeto        = var.projeto
      gerenciado_por = "terraform"
      repositorio    = "github.com/${var.repositorio_github}"
    }
  }
}

data "aws_caller_identity" "atual" {}

locals {
  conta = data.aws_caller_identity.atual.account_id
  # Nome de bucket é global na AWS inteira: o número da conta garante que é único.
  bucket_bruto = "${var.projeto}-bruto-${local.conta}"
  nome_lambda  = "${var.projeto}-coleta"
}
