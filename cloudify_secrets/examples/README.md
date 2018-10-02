```
1) cfy install write-secret-blueprint.yaml -b write_secrets_test -vv
2) cfy secrets list
3) cfy secrets get <secret name>
4) cfy install read-secret-blueprint.yaml -b read_secrets_test -vv
5) cfy deployments outputs read_secrets_test
6) cfy uninstall read_secrets_test -vv
7) cfy uninstall write_secrets_test -vv
8) cfy secrets list
9) cfy secrets delete openstack_config__lab1_tenantA 
10) cfy secrets delete openstack_config__lab1_tenantB 
11) cfy secrets delete openstack_config__lab2_tenantA 
``` 