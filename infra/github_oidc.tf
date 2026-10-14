# GitHub Actions entrando na AWS sem chave guardada (D48). O job pede ao GitHub um token
# OIDC assinado e troca por credenciais temporárias de um papel. A AWS confere a
# assinatura e as condições abaixo; não existe segredo para vazar.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Só este repositório, e só a branch main (execuções agendadas e manuais rodam nela).
    # Um fork ou um pull request não consegue assumir o papel.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repositorio_github}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_leitura" {
  name                 = "${var.projeto}-github-leitura"
  description          = "GitHub Actions (OIDC): só leitura do bruto, para o pacote e o job diário."
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

# Só leitura, só o prefixo bruto/. O job diário e o pacote baixam; quem grava é a Lambda.
data "aws_iam_policy_document" "github_leitura" {
  statement {
    sid       = "ListarBruto"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.bruto.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["bruto/*"]
    }
  }
  statement {
    sid       = "LerBruto"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.bruto.arn}/bruto/*"]
  }
}

resource "aws_iam_role_policy" "github_leitura" {
  name   = "ler-bruto"
  role   = aws_iam_role.github_leitura.id
  policy = data.aws_iam_policy_document.github_leitura.json
}
