resource "vultr_ssh_key" "admin_ssh_key" {
  for_each = var.ssh_keys

  name    = each.key
  ssh_key = each.value
}