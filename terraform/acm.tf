# ACM Certificate — HTTPS for Langfuse ALB

resource "aws_acm_certificate" "alb" {
  count             = var.enable_langfuse && var.route53_zone_id != "" ? 1 : 0
  domain_name       = var.langfuse_host_header
  validation_method = "DNS"

  tags = {
    Name = "${var.project_name}-alb"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "acm_validation" {
  for_each = var.enable_langfuse && var.route53_zone_id != "" ? {
    for dvo in aws_acm_certificate.alb[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60

  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "alb" {
  count                   = var.enable_langfuse && var.route53_zone_id != "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.alb[0].arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation : record.fqdn]
}
