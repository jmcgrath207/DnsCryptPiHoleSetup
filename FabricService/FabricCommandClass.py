from fabric.api import sudo, cd, run
from fabric.contrib.files import append as fabappend, exists, comment
import re
import ipaddress
from CsvService.CsvClass import CsvClass
from FabricService.StringContainer import DnsCryptService, DnsCryptSocket, DnsCryptConf



class FabricCommandClass(CsvClass):



    def CommandSystemPackages(self):
        requiredPackages = "build-essential tcpdump dnsutils libsodium-dev locate " \
                           "bash-completion libsystemd-dev pkg-config python3-dev rng-tools"
        returnCode = run("dpkg -l " + requiredPackages)
        if(returnCode.failed):
            sudo('sudo apt-get update')
            sudo('apt-get -y install ' + requiredPackages)



    def CommandBuildDNSCrypt(self):
        DnsCryptExractDir = FabricCommandClass.CommandBuildDNSCrypt.DnsCryptExractDir
        DnsCryptDownloadLink = FabricCommandClass.CommandBuildDNSCrypt.DnsCryptDownloadLink
        returnCode = run("which dnscrypt-proxy")
        if(returnCode.failed):
            with cd(DnsCryptExractDir):
                run('wget' + DnsCryptDownloadLink)
                run('tar -xf dnscrypt*.tar.gz -C dnscryptBuild --strip-components=1')
            with cd(DnsCryptExractDir + "/dnscryptBuild/"):
                sudo("ldconfig")
                run("./configure --with-systemd")
                run("make")
                sudo("make install")
        else:
            run("mkdir -p " + DnsCryptExractDir + "/dnscryptBuild/")

    def CommandAddDnsCryptUser(self):
        returnCode = run("id -u dnscrypt")
        if(returnCode.failed):
            sudo("useradd -r -d /var/dnscrypt -m -s /usr/sbin/nologin dnscrypt")


    def CommandUpdateDnsCryptResolvers(self):
        DnsCryptResolverCsvLink = FabricCommandClass.CommandUpdateDnsCryptResolvers.DnsCryptResolverCsvLink
        DnsCryptResolverDir = FabricCommandClass.CommandUpdateDnsCryptResolvers.DnsCryptResolverDir
        with cd(DnsCryptResolverDir):
            sudo("wget -N " + DnsCryptResolverCsvLink)


    def CommandCreateDNSCryptProxies(self) -> list:

        DnsCryptResolverDir =  FabricCommandClass.CommandCreateDNSCryptProxies.DnsCryptResolverDir
        DnsCryptResolverNames = FabricCommandClass.CommandCreateDNSCryptProxies.DnsCryptResolverNames
        DnsCryptResolverCsvLink = FabricCommandClass.CommandCreateDNSCryptProxies.DnsCryptResolverCsvLink
        LoopBackStartAddress  = FabricCommandClass.CommandCreateDNSCryptProxies.LoopBackStartAddress
        DnsCryptExractDir = FabricCommandClass.CommandCreateDNSCryptProxies.DnsCryptExractDir

        AvailableResolvers = self.GetDnsCryptProxyNames(DnsCryptResolverDir)



        # Check if Resolver Name is Correct

        for name in DnsCryptResolverNames:
            if name not in AvailableResolvers:
                raise ValueError(name + ' Is not a Vaild Resolver Name. Please Check ' + DnsCryptResolverCsvLink + ' to ensure the name is correct')

        # Clear Old Files

        with cd(DnsCryptExractDir + "/dnscryptBuild/"):
            run("rm dnscrypt-proxy@*")

        # Find a Avaible Socket LoopBack Address and Create Socket Files

        ListenAddresses = []
        runningSockets = sudo("ss -nlut | awk 'NR>1 {print  $5}'")
        runningSockets = re.sub(r".*[a-zA-Z]+\S","",runningSockets).split()
        for name in DnsCryptResolverNames:
            with cd(DnsCryptExractDir + "/dnscryptBuild/"):
                while True:
                    if LoopBackStartAddress + ":41" not in runningSockets:
                        fabappend("dnscrypt-proxy@" + name + ".socket", DnsCryptSocket.format(LoopBackStartAddress))
                        runningSockets.append(LoopBackStartAddress + ":41")
                        ListenAddresses.append(LoopBackStartAddress)
                        break
                    LoopBackStartAddress = str(ipaddress.ip_address(LoopBackStartAddress) + 1)
                    if LoopBackStartAddress == '127.255.255.254':
                        raise ValueError("No Ip address available in the 127.0.0.0/8 IPV4 Range")


        ### Stop and Remove Old Dns Proxy Services
        sudo("systemctl stop dnscrypt-proxy@\*")
        sudo("systemctl disable dnscrypt-proxy@\*")
        sudo("rm /etc/systemd/system/multi-user.target.wants/dnscrypt-proxy*")
        sudo("rm /etc/systemd/system/sockets.target.wants/dnscrypt-proxy*")
        sudo("rm /etc/systemd/system/dnscrypt-proxy*")
        sudo("systemctl daemon-reload")
        sudo("systemctl reset-failed")



        # Create Service then start and enable them
        with cd(DnsCryptExractDir + "/dnscryptBuild/"):
            fabappend('dnscrypt-proxy@.service',DnsCryptService)
            sudo("cp ./dnscrypt-proxy@* /etc/systemd/system/.")
        sudo("systemctl daemon-reload")
        for name in DnsCryptResolverNames:
            sudo("systemctl enable dnscrypt-proxy@" + name + ".socket")
            sudo("systemctl enable dnscrypt-proxy@" + name + ".service")
            sudo("systemctl start dnscrypt-proxy@" + name + ".socket")
            sudo("systemctl start dnscrypt-proxy@" + name + ".service")

        return ListenAddresses




    def CommandChangeDnsMasq(self):

        DnsCryptResolverNames = FabricCommandClass.CommandChangeDnsMasq.DnsCryptResolverNames
        ListenAddresses = FabricCommandClass.CommandChangeDnsMasq.ListenAddresses
        host = FabricCommandClass.CommandChangeDnsMasq.host

        ListenAddresses = ListenAddresses[host]
        with cd("/etc/dnsmasq.d"):
            sudo("rm -f 02-dnscrypt.conf")
            ConfListenAddresses = ["server=" + ListenAddress + "#41" for ListenAddress in ListenAddresses]
            ConfListenAddresses = '\n'.join(ConfListenAddresses)
            fabappend('02-dnscrypt.conf', DnsCryptConf.format(ConfListenAddresses),use_sudo=True)

        comment('/etc/dnsmasq.d/01-pihole.conf', r'server=.*', use_sudo=True, backup='')
        comment('/etc/pihole/setupVars.conf', r'PIHOLE_DNS.*',use_sudo=True,backup='')
        sudo("sed -i 's/.*dnscrypt.*//g' /etc/hosts")
        ## TODO: need to change Foward Detination Logs in Pihole
        for name,address in zip(DnsCryptResolverNames,ListenAddresses):
            sudo("sh -c 'echo \"{0}\t{1} \" >> /etc/hosts'".format(address,name + "-dnscrypt"))




        sudo("service dnsmasq restart")









