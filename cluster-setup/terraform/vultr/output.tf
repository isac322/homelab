output "ip_backbone_master" {
  value     = vultr_instance.backbone-master.main_ip
  sensitive = true
}