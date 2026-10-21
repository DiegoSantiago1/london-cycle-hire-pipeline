# Consultas SQL direto no bruto do S3 (D50): Glue Data Catalog + Athena.
#
#   S3 bruto (JSON gzip, intocado) ──► tabela do Glue (uma linha de texto por retrato)
#                                        └─► views no Athena (uma linha por estação)
#
# Sem crawler (cobra por DPU-hora): a tabela é declarada aqui e as partições vêm por
# projeção (partition projection), calculadas a partir do nome da pasta data=AAAA-MM-DD.
# Custo: o Athena cobra US$ 5 por TB lido; um dia de retratos tem ~8 MB comprimidos.

locals {
  bucket_athena = "${var.projeto}-athena-${local.conta}"
  banco_glue    = replace(var.projeto, "-", "_")
}

# Resultados das consultas: bucket separado, para o bruto continuar só com o bruto.
resource "aws_s3_bucket" "athena" {
  bucket = local.bucket_athena
}

resource "aws_s3_bucket_public_access_block" "athena" {
  bucket                  = aws_s3_bucket.athena.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "athena" {
  bucket = aws_s3_bucket.athena.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena" {
  bucket = aws_s3_bucket.athena.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Resultado de consulta é descartável: apagado depois de 7 dias.
resource "aws_s3_bucket_lifecycle_configuration" "athena" {
  bucket = aws_s3_bucket.athena.id
  rule {
    id     = "resultados-descartaveis"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "athena_so_tls" {
  statement {
    sid     = "SoHTTPS"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.athena.arn,
      "${aws_s3_bucket.athena.arn}/*",
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

resource "aws_s3_bucket_policy" "athena" {
  bucket     = aws_s3_bucket.athena.id
  policy     = data.aws_iam_policy_document.athena_so_tls.json
  depends_on = [aws_s3_bucket_public_access_block.athena]
}

# Grupo de trabalho com trava de custo: nenhuma consulta lê mais que o limite (D50).
resource "aws_athena_workgroup" "consultas" {
  name          = var.projeto
  description   = "Consultas SQL no bruto do S3, com limite de bytes lidos por consulta."
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_limite_bytes

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena.id}/resultados/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_glue_catalog_database" "bicicletas" {
  name        = local.banco_glue
  description = "Catálogo do bruto ao vivo das bicicletas de Londres (TfL BikePoint)."
}

# Cada retrato é um arquivo .json.gz com UMA linha: a lista JSON das ~800 estações.
# A tabela lê essa linha como texto (coluna `linha`); quem abre o JSON é a view
# (athena/01_view_estacoes.sql), com json_parse + UNNEST. Assim a tabela nunca quebra se
# a TfL acrescentar um campo: o bruto continua sendo lido do jeito que chegou.
resource "aws_glue_catalog_table" "retratos" {
  name          = "retratos"
  database_name = aws_glue_catalog_database.bicicletas.name
  description   = "Retratos brutos da API BikePoint, um por arquivo, coletados a cada 15 minutos."
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                        = "TRUE"
    classification                  = "text"
    compressionType                 = "gzip"
    "projection.enabled"            = "true"
    "projection.data.type"          = "date"
    "projection.data.format"        = "yyyy-MM-dd"
    "projection.data.range"         = "${var.athena_inicio_bruto},NOW"
    "projection.data.interval"      = "1"
    "projection.data.interval.unit" = "DAYS"
    "storage.location.template"     = "s3://${aws_s3_bucket.bruto.id}/bruto/bikepoint/data=$${data}/"
  }

  partition_keys {
    name    = "data"
    type    = "string"
    comment = "Dia da coleta (UTC), tirado da pasta data=AAAA-MM-DD."
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.bruto.id}/bruto/bikepoint/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe"
      parameters = {
        # Um caractere que nunca aparece no JSON: a linha inteira vira uma coluna só.
        "field.delim"          = "\u0001"
        "serialization.format" = "\u0001"
      }
    }

    columns {
      name    = "linha"
      type    = "string"
      comment = "O retrato inteiro, como a API devolveu (lista JSON das estações)."
    }
  }
}
