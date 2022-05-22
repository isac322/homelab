output "ip_backbone_master" {
  value     = vultr_instance.backbone_master.main_ip
  sensitive = true
}