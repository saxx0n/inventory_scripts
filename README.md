This is a (soon to be) collection of inventory generating scripts, based on upstream providers.  

ProxMox:
 - This was built and tested against AAP 4.4, but should work against AWX of a similar version.  It does NOT require additional modules and works with the out-of-the-box EE.
 - It will create inventory-groups based on ProxMox tags, stripping out any numbers and adding "_servers" to the end of them.
   - "Ubuntu24.04" will become "ubuntu_servers" for example
 - To use:
   - Create a new credentail of type "Red Hat Ansible Automation Platform" and put your proxmox details into it (We are abusing it to pass credentails).  You should NOT be using the root user, as show in the below screenshot.
   ![image](https://github.com/user-attachments/assets/97e4bc38-eb0c-48ef-aa1c-2f93698f4f73)
   - Create a new inventory source with the following values (adjust value as needed to match your environment
  ![image](https://github.com/user-attachments/assets/796d9c7a-254c-4153-a9cc-9506ea8a0d04)

