# Versões fixadas: o mesmo código gera a mesma infraestrutura em qualquer máquina.
# O .terraform.lock.hcl (versionado) trava também o hash de cada provedor.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Estado local (infra/terraform.tfstate, fora do git). Uma pessoa só aplica a
  # infraestrutura, e o arquivo fica na pasta do OneDrive, com cópia. Um backend S3 com
  # trava seria o passo seguinte se mais gente aplicasse (docs/DECISOES.md D46).
}
