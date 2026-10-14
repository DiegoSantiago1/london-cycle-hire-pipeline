# Data lake do bruto ao vivo. Imutável na prática por três camadas (D45):
# 1. a Lambda grava com If-None-Match: * (o S3 recusa sobrescrever uma chave);
# 2. a Lambda só tem s3:PutObject (não apaga nem lê);
# 3. versionamento: mesmo um erro humano deixa a versão anterior recuperável.

resource "aws_s3_bucket" "bruto" {
  bucket = local.bucket_bruto
}

resource "aws_s3_bucket_public_access_block" "bruto" {
  bucket                  = aws_s3_bucket.bruto.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Sem ACLs: quem manda é só a política do IAM e a do bucket.
resource "aws_s3_bucket_ownership_controls" "bruto" {
  bucket = aws_s3_bucket.bruto.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "bruto" {
  bucket = aws_s3_bucket.bruto.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bruto" {
  bucket = aws_s3_bucket.bruto.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # chave gerenciada pelo S3: sem custo do KMS
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "bruto" {
  bucket = aws_s3_bucket.bruto.id

  rule {
    id     = "limpeza"
    status = "Enabled"
    filter {}

    # Versão antiga só existe se alguém apagar ou regravar por fora: 30 dias para recuperar.
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.bruto]
}

# Só HTTPS: qualquer acesso sem TLS é recusado, mesmo com credencial válida.
data "aws_iam_policy_document" "bruto_so_tls" {
  statement {
    sid     = "SoHTTPS"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.bruto.arn,
      "${aws_s3_bucket.bruto.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "bruto" {
  bucket = aws_s3_bucket.bruto.id
  policy = data.aws_iam_policy_document.bruto_so_tls.json

  depends_on = [aws_s3_bucket_public_access_block.bruto]
}
