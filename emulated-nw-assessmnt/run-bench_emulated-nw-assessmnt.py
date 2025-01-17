##############################################################################################
##      Title:          Post-Quantum TLS Handshake Benchmarker                              ##
##                                                                                          ##
##      Author:         Joshua Drexel, HSLU, Switzerland                                    ##
##                                                                                          ##
##      Description:    Benchmarking Post-Quantum TLS Handshake performance using           ##
##                      different signature algorithms with s_timer.                        ##
##                                                                                          ##
##      Prerequisites:                                                                      ##
##                      - Have the OQS-Provider for OpenSSL installed.                      ##
##                      - Have PATH and LD_LIBRARY_PATH adjusted to point to the OpenSSL    ##
##                        version, which has the OQS-Provider activated                     ##
##                        (if multiple OpenSSL versions are installed).                     ##
##############################################################################################

import argparse
import os
import sys
import subprocess
import shutil
import time
from datetime import datetime

# Path to s_timer binary
STIMER_BINARY = "./tls-client/s_timer"
# Path to namespace setup script
NSPACE_SETUP = "./virt-test-env/namespace-setup.sh"
# Path to namespace cleanup script
NSPACE_CLEANUP = "./virt-test-env/namespace-cleanup.sh"
# Path to general OpenSSL config file
OSSL_CONFIG = "./emulated-nw-assessmnt/oqs-openssl.cnf"
# Path to OpenSSL RCA config file
OSSL_RCA_CONFIG = "./emulated-nw-assessmnt/oqs-openssl-rca.cnf"
# Path to OpenSSL ICA config file
OSSL_ICA_CONFIG = "./emulated-nw-assessmnt/oqs-openssl-ica.cnf"

# Sample size per iteration
# Note: The number of rounds provided as argument to this script is split up in SAMPLE_SIZE chunks.
SAMPLE_SIZE = 1

# Maximum duration in seconds for a single handshake (used for timeout)
MAX_HS_DUR = 30

# List of the traditional algorithms used for reference
# Uncomment if an algorithm should be included in the test
TRADITIONAL_SIG_ALGS = []
#TRADITIONAL_SIG_ALGS.append("ED448")
#TRADITIONAL_SIG_ALGS.append("ED25519")
#TRADITIONAL_SIG_ALGS.append("RSA:2048")
#TRADITIONAL_SIG_ALGS.append("RSA:3072")
#TRADITIONAL_SIG_ALGS.append("ECDSAprime256v1")
#TRADITIONAL_SIG_ALGS.append("ECDSAsecp384r1")

# Lists of Bitrate FLOAT (Mbit/s), Delay FLOAT (ms) and Packet Loss Rate FLOAT (percent) values to be emulated
# The delay will be added to both veth devices, therefore RTT is approx. twice the delay
RATE_VALUES = [10000.0]
DELAY_VALUES = [0.0,5.0,50.0]
LOSS_VALUES = [0,0.1,1.0]

def run_benchmark_test(retry):
    # Prepare file paths
    ca_cert = pki_path+"/ca/ca.crt"
    ica_cert = pki_path+"/ica/ica.crt"
    server_cert = pki_path+"/server/server.crt"
    server_key = pki_path+"/server/server.key"
    client_cert = pki_path+"/client/client.crt"
    client_key = pki_path+"/client/client.key"
    
    # If record flag is set, prepare Wireshark file for traffic dump
    if record_traffic:
        traffic_recordings_file_name_server = wireshark_folder_path+"/server-"+algname+"_Rate-"+str(rate)+"_Delay-"+str(delay)+"_Loss-"+str(loss)+"_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".pcap"
        dump_file = open(traffic_recordings_file_name_server, "a")
        dump_file.close()
        
        traffic_recordings_file_name_client = wireshark_folder_path+"/client-"+algname+"_Rate-"+str(rate)+"_Delay-"+str(delay)+"_Loss-"+str(loss)+"_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".pcap"
        dump_file = open(traffic_recordings_file_name_client, "a")
        dump_file.close()
        
        # Prepare tls session secrets file for later traffic decryption in Wireshark
        session_secrets_file_name = wireshark_folder_path+"/"+algname+"_Rate-"+str(rate)+"_Delay-"+str(delay)+"_Loss-"+str(loss)+"_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".secrets"
        secrets_file = open(session_secrets_file_name, "a")
        secrets_file.close()

        
        # Give "others" write permissions to recording file, otherwise tshark cannot record traffic (if the file is in a user's home-dir)
        os.chmod(traffic_recordings_file_name_server, 0o666)
        os.chmod(traffic_recordings_file_name_client, 0o666)


        # Start wireshark process in namespace ns1 (server)
        # Note: Use Popen, as the process needs to run in background
        wireshark_server = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', 'ns1', 'tshark', '-i', 'veth101', '-w', traffic_recordings_file_name_server], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
        # Wait for wireshark to start
        time.sleep(2)
    
        if wireshark_server is None:
            print('\033[1;31mERROR:\t\tFailure during start of wireshark for server. Aborting.\033[0m', file=sys.stderr)
            sys.exit(-1)
            
        # Start wireshark process in namespace ns2 (client)
        # Note: Use Popen, as the process needs to run in background
        wireshark_client = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', 'ns2', 'tshark', '-i', 'veth102', '-w', traffic_recordings_file_name_client], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
        # Wait for wireshark to start
        time.sleep(2)
    
        if wireshark_client is None:
            print('\033[1;31mERROR:\t\tFailure during start of wireshark for client. Aborting.\033[0m', file=sys.stderr)
            sys.exit(-1)
    

    #Split in SAMPLE_SIZE-chunks of rounds to fail faster and repeat the execution if TIMEOUT is reached
    open_rounds = rounds
    output_iterator = 1
    
    while(open_rounds > 0):
        
        if(open_rounds - SAMPLE_SIZE >= 0):
            # Another full SAMPLE_SIZE-rounds chunk to go
            run_rounds = SAMPLE_SIZE
            open_rounds = open_rounds - SAMPLE_SIZE
        else:
            # Run a last time with the left-over rounds to go
            run_rounds = open_rounds
            open_rounds = 0
    
    
        # Start s_server process in namespace ns1     
        if record_traffic:
            tls_server = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', 'ns1', 'openssl', 's_server', '-cert', server_cert, '-key', server_key, '-tls1_3', '-Verify', '2', '-verify_return_error', '-CAfile', ca_cert, '-chainCAfile', ica_cert, '-ignore_unexpected_eof', '-keylogfile', session_secrets_file_name, '-quiet'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            tls_server = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', 'ns1', 'openssl', 's_server', '-cert', server_cert, '-key', server_key, '-tls1_3', '-verify', '2', '-verify_return_error', '-CAfile', ca_cert, '-chainCAfile', ica_cert, '-ignore_unexpected_eof', '-quiet'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server to start
        time.sleep(0.2)
        
        # Check if process start was successful
        if tls_server is None:
            print('\033[1;31mERROR:\t\tFailure during start of TLS server. Aborting.\033[0m', file=sys.stderr)
            sys.exit(-1)
        
        
        
        # Start s_timer process in namespace ns2        
        tls_client = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', 'ns2', STIMER_BINARY, '-h', '192.168.101.1:4433', '-r', str(run_rounds), '--cert='+client_cert, '--key='+client_key, '--rootcert='+ca_cert, '--chaincert='+ica_cert, '--config='+OSSL_CONFIG], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # It is assumed that no more than MAX_HS_DUR seconds per handshake are required.
        timeout = MAX_HS_DUR * run_rounds
        
        try:
            tls_client.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f'\033[1;31mERROR:\t\tTimeout reached for {alg} with rate of {rate}, {delay}ms delay and {loss}% packet loss. Repeating the test.\033[0m', file=sys.stderr)
            
            # End all processes
            tls_server.terminate()
            tls_client.terminate()
            
            # Adding up the failed rounds and start again
            open_rounds = open_rounds + run_rounds
            
            continue
    
    
        # Save output line by line in array
        s_time_output = bytes.decode(tls_client.stdout.read(), 'utf-8').splitlines()
            
        # Check that OpenSSL 3.2.0 was used (no older version)
        # Note: s_timer outputs the OpenSSL version in the first output line
        
        if s_time_output[0].find('OpenSSL 3.2.0 ') < 0:
            # Correct version string not found, abort
            print('\033[1;31mERROR:\t\tWrong OpenSSL version in s_timer. Aborting.\033[0m', file=sys.stderr)
            sys.exit(-1)
        else:
            # Check if provider could be loaded successfully
            # Note: s_timer output if provider load was successful on the second line
            if s_time_output[1].find('provider loaded successfully') < 0:
                # Provider not found
                print('\033[1;31mERROR:\t\tOQS-Provider in s_timer not loaded. Aborting.\033[0m', file=sys.stderr)
                sys.exit(-1)
            else:
                # Provider loaded successfully, print results
                for result in s_time_output[2].split(","):
                    # s_timer outputs results as pairs of measurement:success (float:bool)
                    # Note: If connection was unsuccessful (success=false), a dummy value of 0.0ms is returned as measurement
                    measurement, success = result.split(":")
                    results_file = open(results_file_name, "a")
                    results_file.write(alg+","+str(output_iterator)+","+str(rate)+","+str(delay)+","+str(loss)+","+success+","+measurement+"\n")
                    results_file.close()
                    output_iterator = output_iterator + 1
                
                print('\033[1;32mSUCCESS:\tOpen Rounds: {}. Results for {} with {}mbit rate limit, {}ms delay and {}% packet loss written to file.\n\033[0m'.format(open_rounds, alg, rate, delay, loss), file=sys.stdout)
        
        # Terminate TLS server process
        tls_server.terminate()
    
        # End of while loop
    
    
    if record_traffic:
        time.sleep(2)
        wireshark_server.terminate()
        wireshark_client.terminate()
    
    return

def pki_setup(alg, algname, out_dir):
    
    # Prepare parent directory for algorithm specific PKI
    pki_path = os.path.join(out_dir, "pki-{}".format(algname))
    create_dir(pki_path)
    ca_config = pki_path+"/oqs-openssl-ca.cnf"
    ica_config = pki_path+"/oqs-openssl-ica.cnf"             
    
    # Create sub-directory for CA, prepare file paths, create and init serial-number file
    ca_path = os.path.join(pki_path, "ca")
    create_dir(ca_path)
    ca_cert = ca_path+"/ca.crt"
    ca_key = ca_path+"/ca.key"
    serial_file = open(ca_path+"/serial", "a")
    serial_file.write("1000")
    serial_file.close()
    index_file = open(ca_path+"/index.txt", "a")
    index_file.close()
    # Copy CA config, but set real CA path
    with open(OSSL_RCA_CONFIG, "rt") as template_config:
        with open(ca_config, "wt") as new_config:
            for line in template_config:
                new_config.write(line.replace('{path}', ca_path))
    
    # Create sub-directory for ICA, prepare file paths, create and init serial-number file
    ica_path = os.path.join(pki_path, "ica")
    create_dir(ica_path)
    ica_cert = ica_path+"/ica.crt"
    ica_csr = ica_path+"/ica.csr"
    ica_key = ica_path+"/ica.key"
    file = open(ica_path+"/serial", "a")
    file.write("1000")
    file.close()
    index_file = open(ica_path+"/index.txt", "a")
    index_file.close()
    # Copy ICA config, but set real ICA path
    with open(OSSL_ICA_CONFIG, "rt") as template_config:
        with open(ica_config, "wt") as new_config:
            for line in template_config:
                new_config.write(line.replace('{path}', ica_path))
    
    
    # Create sub-directory for server certificate, prepare file paths
    server_path = os.path.join(pki_path, "server")
    create_dir(server_path)
    server_cert = server_path+"/server.crt"
    server_csr = server_path+"/server.csr"
    server_key = server_path+"/server.key"
    
    # Create sub-directory for client certificate, prepare file paths
    client_path = os.path.join(pki_path, "client")
    create_dir(client_path)
    client_cert = client_path+"/client.crt"
    client_csr = client_path+"/client.csr"
    client_key = client_path+"/client.key"
    
    ####################################################################
    # Create CA key and certificate
    # Note: if/else is needed, because ECDSA needs additional arguments than EdDSA, RSA and PQC
    if alg.startswith("ECDSA"):
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg[5:]+" - Test Root CA"
        ec_param = 'ec_paramgen_curve:'+alg[5:]
        ca_cert_process = subprocess.run(['openssl', 'req', '-x509', '-new', '-sha256', '-newkey', 'ec', '-pkeyopt', ec_param, '-keyout', ca_key, '-out', ca_cert, '-nodes', '-subj', subject, '-days', '7300', '-extensions', 'v3_ca', '-config', ca_config], capture_output = True, text = True)
    else:
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg+" - Test Root CA"
        ca_cert_process = subprocess.run(['openssl', 'req', '-x509', '-new', '-sha256', '-newkey', alg, '-keyout', ca_key, '-out', ca_cert, '-nodes', '-subj', subject, '-days', '7300', '-extensions', 'v3_ca', '-config', ca_config], capture_output=True, text = True)
    
    
    if ca_cert_process.returncode != 0:
        # Print the error messages from subprocess
        print(ca_cert_process.stderr)
        print('\033[1;31mERROR:\t\tError during CA setup. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
    
    
    ####################################################################
    # Create Intermediate-CA key, CSR and certificate
    if alg.startswith("ECDSA"):
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg[5:]+" - Test Intermediate CA"
        ica_key_process = subprocess.run(['openssl', 'ecparam', '-name', alg[5:], '-genkey', '-out', ica_key,], capture_output=True, text = True)
    else:
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg+" - Test Intermediate CA"
        ica_key_process = subprocess.run(['openssl', 'genpkey', '-algorithm', alg, '-out', ica_key, '-config', ica_config], capture_output=True, text = True)
    
    ica_csr_process = subprocess.run(['openssl', 'req', '-new', '-sha256', '-key', ica_key, '-out', ica_csr, '-subj', subject, '-config', ica_config], capture_output=True, text = True)        
    ica_cert_process = subprocess.run(['openssl', 'ca', '-extensions', 'v3_intermediate_ca', '-md', 'sha256', '-batch', '-in', ica_csr, '-out', ica_cert, '-days', '3650', '-config', ca_config], capture_output=True, text = True)
    
    
    if ica_key_process.returncode != 0 or ica_csr_process.returncode != 0 or ica_cert_process.returncode != 0:
        # Print the error messages from subprocess
        print(ica_key_process.stderr)
        print(ica_csr_process.stderr)
        print(ica_cert_process.stderr)
        print('\033[1;31mERROR:\t\tError during ICA setup. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
        
    
    ####################################################################
    # Create Server key, CSR and certificate
    if alg.startswith("ECDSA"):
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg[5:]+" - Server Certificate"
        server_key_process = subprocess.run(['openssl', 'ecparam', '-name', alg[5:], '-genkey', '-out', server_key,], capture_output=True, text = True)
    else:
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg+" - Server Certificate"
        server_key_process = subprocess.run(['openssl', 'genpkey', '-algorithm', alg, '-out', server_key, '-config', ica_config], capture_output=True, text = True)
    
    server_csr_process = subprocess.run(['openssl', 'req', '-new', '-sha256', '-key', server_key, '-out', server_csr, '-subj', subject, '-config', ica_config], capture_output=True, text = True)        
    server_cert_process = subprocess.run(['openssl', 'ca', '-extensions', 'server_cert', '-md', 'sha256', '-batch', '-in', server_csr, '-out', server_cert, '-days', '365', '-config', ica_config], capture_output=True, text = True)
    
    
    if server_key_process.returncode != 0 or server_csr_process.returncode != 0 or server_cert_process.returncode != 0:
        # Print the error messages from subprocess
        print(server_key_process.stderr)
        print(server_csr_process.stderr)
        print(server_cert_process.stderr)
        print('\033[1;31mERROR:\t\tError during server certificate setup. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
    
    
    ####################################################################
    # Create Client key, CSR and certificate
    if alg.startswith("ECDSA"):
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg[5:]+" - Client Certificate"
        client_key_process = subprocess.run(['openssl', 'ecparam', '-name', alg[5:], '-genkey', '-out', client_key,], capture_output=True, text = True)
    else:
        subject = "/C=CH/ST=Zug/L=Rotkreuz/O=Lucerne University of Applied Sciences and Arts/OU=Applied Cyber Security Research Lab/CN="+alg+" - Client Certificate"
        client_key_process = subprocess.run(['openssl', 'genpkey', '-algorithm', alg, '-out', client_key, '-config', ica_config], capture_output=True, text = True)
    
    client_csr_process = subprocess.run(['openssl', 'req', '-new', '-sha256', '-key', client_key, '-out', client_csr, '-subj', subject, '-config', ica_config], capture_output=True, text = True)        
    client_cert_process = subprocess.run(['openssl', 'ca', '-extensions', 'server_cert', '-md', 'sha256', '-batch', '-in', client_csr, '-out', client_cert, '-days', '365', '-config', ica_config], capture_output=True, text = True)
    
    
    if client_key_process.returncode != 0 or client_csr_process.returncode != 0 or client_cert_process.returncode != 0:
        # Print the error messages from subprocess
        print(client_key_process.stderr)
        print(client_csr_process.stderr)
        print(client_cert_process.stderr)
        print('\033[1;31mERROR:\t\tError during server certificate setup. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
    
    return

def namespaces_setup(retry):
    
    print('\033[1;34mINFO:\t\tSetting up namespaces.\033[0m', file=sys.stdout)
    
    ns_process = subprocess.run(["bash", NSPACE_SETUP], capture_output=True)
    
    if ns_process.returncode != 0 and retry == False:
        print('\033[1;33mWARNING:\tError during namespace setup. Will do cleanup and retry again.\033[0m', file=sys.stdout)
        namespaces_cleanup()
        namespaces_setup(True)
    elif ns_process.returncode != 0 and retry == True:
        print('\033[1;31mERROR:\t\tFailure during namespace setup. Cleanup did not help. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
    
    return

def namespaces_cleanup():
    
    print('\033[1;34mINFO:\t\tCleaning up namespaces.\033[0m', file=sys.stdout)
    
    ns_process = subprocess.run(["bash", NSPACE_CLEANUP], capture_output=True)

    if ns_process.returncode != 0:
        print('\033[1;31mERROR:\t\tFailure during namespace cleanup. Aborting.\033[0m', file=sys.stderr)
        sys.exit(-1)
    
    return

def read_pq_sigalgs(sig_file):
    
    algs_from_file=[]
    algs_supported=[]
    
    # First get the list of supported signature algorithms of the OpenSSL installation
    process = subprocess.run(["openssl", "list", "-signature-algorithms"], capture_output=True)

    for line in process.stdout.splitlines():
        l = str(line.rstrip())[2:-1]
        if l.endswith(" @ oqsprovider"):
            algs_supported.append(l[2:-14]) 
    
    # Get the signature algorithms from the file and check if they are supported, otherwise exclude from list
    with open(sig_file, 'r', encoding='UTF-8') as file:
        while line := file.readline():
            algname = line.rstrip()
            if algname in algs_supported:
                # Algorithm is supported, add it to the list
                algs_from_file.append(line.rstrip())
            else:
                print('\033[1;33mWARNING:\tAlgorithm "{}" not supported, removed from list.\033[0m'.format(algname), file=sys.stderr)
        
        # Check if there are signature algorithms found in the file provided, otherwise exit with error
        if not algs_from_file:
            print('\033[1;31mERROR:\t\tNo supported algorithms found in "{}". Aborting.\033[0m'.format(sig_file), file=sys.stderr)
            file.close()
            sys.exit(-1)
    file.close()
    return algs_from_file

def create_dir(path):
    if not os.path.exists(path):
        os.mkdir(path)
    else:
        overwriting = ask_for_overwrite(path)
        
        if overwriting == "yes":
            # Delete directory and all contained subdirs and files
            shutil.rmtree(path)
            
            # Re-create the directory
            os.mkdir(path)
            print('\033[1;34mINFO:\t\tFile/Directory "{}" overwritten.\033[0m'.format(path), file=sys.stdout)
        elif overwriting == "no":
            print('\033[1;34mINFO:\t\tFile/Directory "{}" is not overwritten.\033[0m'.format(path), file=sys.stdout)
        else:
            print('\033[1;31mERROR:\t\tFailure during file/directory operation. Aborting.\033[0m', file=sys.stderr)
            sys.exit(-1)
    return

def ask_for_overwrite(path):
    yes = {'yes','y', 'ye'}
    no = {'no','n', ''}
    
    choice = input('Directory or file "{}" already exists. Should it be overwritten (ALL subdirectories and files will be lost!)? [y/N] '.format(path)).lower()
    
    if choice in yes:
       return "yes"
    elif choice in no:
       return "no"
    else:
       print('\033[1;34mINFO:\t\tPlease respond with yes or no.\033[0m', file=sys.stdout)
       ask_for_overwrite(path)
    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='Post-Quantum TLS Handshake Benchmarker',
        description='Benchmarking Post-Quantum TLS Handshake performance using different signature algorithms with OpenSSL s_time.')
    parser.add_argument('-rounds', help='the number of times the test should be performed for, default is 10', metavar='INT', type=int, default='10', required=False)
    parser.add_argument('-sigs', help='path to file with list of PQ signature algorithms to be included in the tests', metavar='<file path>', required=True)
    parser.add_argument('-out', help='path to directory where the results should be saved to', metavar='<dir path>', required=True)
    parser.add_argument('-rec', help='if set, the TLS traffic is dumped to a file and the session secrets are exported', action='store_true', required=False)
    
    args = parser.parse_args()
    
    rounds = args.rounds
    sig_file = args.sigs
    out_dir = args.out
    record_traffic = args.rec
    
    # Make sure that the PQ signature algorithm file exists
    if not os.path.isfile(sig_file):
        print('\033[1;31mERROR:\t\tFile "{}" does not exist. Please provide a file with the post-quantum signature algorithms to be included in the tests.\033[0m'.format(sig_file), file=sys.stderr)
        sys.exit(-1)
    
    # Check if output directory exists
    if not os.path.isdir(out_dir):
        print('\033[1;31mERROR:\t\tDirectory "{}" does not exist. Please provide a directory to store the resulting files in.\033[0m'.format(out_dir), file=sys.stderr) 
        sys.exit(-1)
    
    # Prepare file for benchmark results
    results_file_name = out_dir+"results_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".csv"
    results_file = open(results_file_name, "a")
    results_file.write("Signature Algorithm,Test Round,Rate Limit,Delay,Packet Loss,Success,Handshake Duration [ms]"+"\n")
    results_file.close()
    
    # If traffic is to be recorded, prepare folder
    if record_traffic:
        # Prepare folder for wireshark dump files
        wireshark_folder_path = os.path.join(out_dir, "traffic-recordings")
        create_dir(wireshark_folder_path)
        
    # Read the post-quantum signature algorithms from file and check if activated in oqs-provider
    pq_sig_algs = read_pq_sigalgs(sig_file)
    
    # Add the reference algorithms (traditional crypto, provided in global variable) to the list
    sig_algs = TRADITIONAL_SIG_ALGS + pq_sig_algs
    
    # Setup of namespaces and virtual Ethernet devices
    # Note: Perform a cleanup first, just to make sure to have a clean state
    namespaces_cleanup()
    namespaces_setup(False)
    
    # Initialize network emulation on ns1 and ns2 with rate limit of 10 Gbit/s, 0 delay and 0 packet loss
    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns1', 'tc', 'qdisc', 'add', 'dev', 'veth101', 'root', 'netem', 'rate', '10000.0mbit', 'delay', '0ms', 'loss','0%'])    
    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns2', 'tc', 'qdisc', 'add', 'dev', 'veth102', 'root', 'netem', 'rate', '10000.0mbit', 'delay', '0ms', 'loss','0%'])
    
    # Hard-Code MAC Addresses to prevent ARP resolutions which may cause the processes to hang, especially with high packet loss rates
    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns1', 'ip', 'neighbor', 'add', '192.168.102.1', 'lladdr', '00:00:00:00:00:02', 'nud', 'permanent', 'dev', 'veth101'])
    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns2', 'ip', 'neighbor', 'add', '192.168.101.1', 'lladdr', '00:00:00:00:00:01', 'nud', 'permanent', 'dev', 'veth102'])
     
    # Perform benchmark test for each signature algorithm
    for alg in sig_algs:
        print('\033[1;34mINFO:\t\tSetting up "{}" PKI.\033[0m'.format(alg), file=sys.stdout)
        
        # For RSA, replace ":" with "" for the alg name used in the file paths
        if alg.startswith("RSA"):
            algname = alg.replace(":", "")
        else:
            algname = alg
        
        # Setting up the PKI (CA, ICA and EE certificates)
        pki_setup(alg, algname, out_dir)
        pki_path = os.path.join(out_dir, "pki-{}".format(algname))
        
        print('\033[1;34mINFO:\t\tStarting "{}" benchmark tests.\033[0m'.format(alg), file=sys.stdout)
        # Run s_timer benchmark test for each rate, delay and loss value
        for rate in RATE_VALUES:
            for delay in DELAY_VALUES:
                for loss in LOSS_VALUES:
                    print('\033[1;34mINFO:\t\tRate = {}Mbit/s, Delay = {}ms, Packet Loss Rate = {}%.\033[0m'.format(rate, delay, loss), file=sys.stdout)
                    # Change network emulation to specified delay and loss
                    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns1', 'tc', 'qdisc', 'change', 'dev', 'veth101', 'root', 'netem', 'rate', str(rate)+'mbit', 'delay', str(delay)+'ms', 'loss',str(loss)+'%'])
                    subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns2', 'tc', 'qdisc', 'change', 'dev', 'veth102', 'root', 'netem', 'rate', str(rate)+'mbit', 'delay', str(delay)+'ms', 'loss',str(loss)+'%'])
                    
                    # Execute the test using s_timer
                    run_benchmark_test(0)
        
          
    # Cleaning up namespaces and virtual Ethernet devices
    namespaces_cleanup()
    
    print('\033[1;32mSUCCESS:\tResults were stored in "{}". Finished.\033[0m'.format(results_file_name), file=sys.stdout)
    sys.exit(0)
