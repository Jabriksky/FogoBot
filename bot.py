import requests, base58, base64, time
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.transaction import Transaction
from spl.token.constants import TOKEN_PROGRAM_ID, WRAPPED_SOL_MINT
from solana.system_program import create_account, CreateAccountParams
from spl.token.instructions import (
    initialize_account,
    InitializeAccountParams,
    transfer_checked,
    TransferCheckedParams,
    close_account,
    CloseAccountParams
)

requests.packages.urllib3.disable_warnings()

RPC_URL = "https://testnet.fogo.io/"
EXPLORER = "https://fogoscan.com/tx/"

def print_header(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def print_separator():
    print("-" * 60)

def print_info(label, value):
    print(f"  {label:<25}: {value}")

def print_success(message):
    print(f"\n✅ {message}")

def print_error(message):
    print(f"\n❌ {message}")

def print_warning(message):
    print(f"\n⚠️  {message}")

def rpc_request(method, params=None):
    if params is None:
        params = []
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    res = requests.post(RPC_URL, json=payload, verify=False)
    res.raise_for_status()
    return res.json()

def get_min_rent_exempt_for_token_account():
    size = 165
    resp = rpc_request("getMinimumBalanceForRentExemption", [size])
    return int(resp["result"])

def get_latest_blockhash():
    r = rpc_request("getLatestBlockhash", [{"commitment": "finalized"}])
    return r["result"]["value"]["blockhash"]

def get_fogo_balance(pubkey: str) -> int:
    resp = rpc_request("getBalance", [pubkey, {"commitment": "finalized"}])
    return int(resp["result"]["value"])

def get_spl_fogo_balance(owner: str) -> int:
    resp = rpc_request(
        "getTokenAccountsByOwner",
        [owner, {"mint": str(WRAPPED_SOL_MINT)}, {"encoding": "jsonParsed"}],
    )
    accounts = resp.get("result", {}).get("value", [])
    total = 0
    for ta in accounts:
        amt = int(ta["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        total += amt
    return total

def send_raw_transaction(tx_bytes_b64):
    return rpc_request(
        "sendTransaction",
        [
            tx_bytes_b64,
            {"skipPreflight": False, "preflightCommitment": "finalized", "encoding": "base64"},
        ],
    )

def wrap_fogo(private_key: str, amount_fogo: float):
    print_header("WRAPPING FOGO TO SPL FOGO")
    
    secret_bytes = base58.b58decode(private_key)
    wallet = Keypair.from_secret_key(secret_bytes)
    owner = wallet.public_key
    
    print_info("Wallet Address", str(owner))
    print_separator()

    fogo_balance = get_fogo_balance(str(owner))
    print_info("Current FOGO Balance", f"{fogo_balance/1e9:.9f} FOGO")

    amount = int(amount_fogo * 10**9)
    print_info("Amount to Wrap", f"{amount_fogo:.9f} FOGO")
    
    if fogo_balance < amount:
        print_error("Insufficient FOGO Balance for Wrapping!")
        return None

    resp = rpc_request(
        "getTokenAccountsByOwner",
        [str(owner), {"mint": str(WRAPPED_SOL_MINT)}, {"encoding": "jsonParsed"}],
    )
    token_accounts = resp.get("result", {}).get("value", [])
    
    spl_fogo_account = None
    for ta in token_accounts:
        ata_pubkey = PublicKey(ta["pubkey"])
        spl_fogo_account = ata_pubkey
        break
    
    if not spl_fogo_account:
        print_error("No Existing SPL FOGO Account Found!")
        print_info("Status", "You Need to Create a SPL FOGO Account First!")
        return None

    print_info("Existing SPL FOGO Account", str(spl_fogo_account))
    spl_fogo_balance = get_spl_fogo_balance(str(owner))
    print_info("Current SPL FOGO Balance", f"{spl_fogo_balance/1e9:.9f} SPL FOGO")
    
    print_separator()
    print_info("Status", "Creating Proper Wrap Transaction...")

    temp_account_kp = Keypair()
    temp_account_pub = temp_account_kp.public_key
    
    rent_lamports = get_min_rent_exempt_for_token_account()
    
    create_account_ix = create_account(
        CreateAccountParams(
            from_pubkey=owner,
            new_account_pubkey=temp_account_pub,
            lamports=rent_lamports + amount,
            space=165,
            program_id=TOKEN_PROGRAM_ID,
        )
    )

    init_ix = initialize_account(
        InitializeAccountParams(
            account=temp_account_pub,
            mint=WRAPPED_SOL_MINT,
            owner=owner,
            program_id=TOKEN_PROGRAM_ID,
        )
    )

    transfer_ix = transfer_checked(
        TransferCheckedParams(
            program_id=TOKEN_PROGRAM_ID,
            source=temp_account_pub,
            mint=WRAPPED_SOL_MINT,
            dest=spl_fogo_account,
            owner=owner,
            amount=amount,
            decimals=9,
        )
    )

    close_ix = close_account(
        CloseAccountParams(
            program_id=TOKEN_PROGRAM_ID,
            account=temp_account_pub,
            dest=owner,
            owner=owner,
        )
    )

    tx = Transaction()
    tx.add(create_account_ix, init_ix, transfer_ix, close_ix)

    blockhash = get_latest_blockhash()
    print_info("Latest Blockhash", blockhash[:20] + "...")
    
    tx.recent_blockhash = blockhash
    tx.fee_payer = owner
    tx.sign(wallet, temp_account_kp)

    tx_bytes = tx.serialize()
    tx_b64 = base64.b64encode(tx_bytes).decode("utf-8")

    print_info("Status", "Sending Transaction to Network...")
    resp = send_raw_transaction(tx_b64)
    
    print_separator()
    if "result" in resp:
        print_success("FOGO Successfully Wrapped to SPL FOGO!")

        signature = resp["result"]
        print_info("Transaction Signature", signature)
        print_info("Transaction Explorer", EXPLORER+signature)
        
        time.sleep(3)
        
        new_fogo_balance = get_fogo_balance(str(owner))
        new_spl_fogo_balance = get_spl_fogo_balance(str(owner))
        print_separator()
        print_info("Updated FOGO Balance", f"{new_fogo_balance/1e9:.9f} FOGO")
        print_info("Updated SPL FOGO Balance", f"{new_spl_fogo_balance/1e9:.9f} SPL FOGO")
        
        fogo_change = (new_fogo_balance - fogo_balance) / 1e9
        spl_fogo_change = (new_spl_fogo_balance - spl_fogo_balance) / 1e9
        print_info("FOGO Change", f"{fogo_change:+.9f} FOGO")
        print_info("SPL FOGO Change", f"{spl_fogo_change:+.9f} SPL FOGO")
        
        return str(spl_fogo_account)
    else:
        print_error("Transaction failed!")
        if "error" in resp:
            print(f"Error: {resp['error']}")
        return None

def unwrap_fogo(private_key: str, amount_spl_fogo: float):
    print_header("UNWRAPPING SPL FOGO TO FOGO")
    
    secret_bytes = base58.b58decode(private_key)
    wallet = Keypair.from_secret_key(secret_bytes)
    owner = wallet.public_key
    
    print_info("Wallet Address", str(owner))
    print_separator()

    fogo_balance = get_fogo_balance(str(owner))
    print_info("Current FOGO Balance", f"{fogo_balance/1e9:.9f} FOGO")

    spl_fogo_balance = get_spl_fogo_balance(str(owner))
    print_info("Current SPL FOGO Balance", f"{spl_fogo_balance/1e9:.9f} SPL FOGO")
    
    amount = int(amount_spl_fogo * 10**9)
    print_info("Amount to Unwrap", f"{amount_spl_fogo:.9f} SPL FOGO")
    
    if spl_fogo_balance < amount:
        print_error("Insufficient SPL FOGO Balance for Unwrapping!")
        return

    print_separator()
    print_info("Status", "Preparing Transaction...")

    blockhash = get_latest_blockhash()
    print_info("Latest Blockhash", blockhash[:20] + "...")

    resp = rpc_request(
        "getTokenAccountsByOwner",
        [str(owner), {"mint": str(WRAPPED_SOL_MINT)}, {"encoding": "jsonParsed"}],
    )
    token_accounts = resp.get("result", {}).get("value", [])
    
    source_ata = None
    for ta in token_accounts:
        ta_amount = int(ta["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        if ta_amount > 0:
            source_ata = PublicKey(ta["pubkey"])
            break
            
    if source_ata is None:
        print_error("No SPL FOGO Token Account Found With Balance!")
        return
        
    print_info("Source SPL FOGO Account", str(source_ata))

    temp_account_kp = Keypair()
    temp_account_pub = temp_account_kp.public_key

    rent_lamports = get_min_rent_exempt_for_token_account()
    
    print_info("Status", "Building Transaction...")

    create_account_ix = create_account(
        CreateAccountParams(
            from_pubkey=owner,
            new_account_pubkey=temp_account_pub,
            lamports=rent_lamports,
            space=165,
            program_id=TOKEN_PROGRAM_ID,
        )
    )

    init_ix = initialize_account(
        InitializeAccountParams(
            account=temp_account_pub,
            mint=WRAPPED_SOL_MINT,
            owner=owner,
            program_id=TOKEN_PROGRAM_ID,
        )
    )

    transfer_ix = transfer_checked(
        TransferCheckedParams(
            program_id=TOKEN_PROGRAM_ID,
            source=source_ata,
            mint=WRAPPED_SOL_MINT,
            dest=temp_account_pub,
            owner=owner,
            amount=amount,
            decimals=9,
        )
    )

    close_ix = close_account(
        CloseAccountParams(
            program_id=TOKEN_PROGRAM_ID,
            account=temp_account_pub,
            dest=owner,
            owner=owner,
        )
    )

    tx = Transaction()
    tx.add(create_account_ix, init_ix, transfer_ix, close_ix)
    tx.recent_blockhash = blockhash
    tx.fee_payer = owner
    tx.sign(wallet, temp_account_kp)

    tx_bytes = tx.serialize()
    tx_b64 = base64.b64encode(tx_bytes).decode("utf-8")

    print_info("Status", "Sending Transaction to Network...")
    resp = send_raw_transaction(tx_b64)
    
    print_separator()
    if "result" in resp:
        print_success("SPL FOGO Successfully Unwrapped to FOGO!")

        signature = resp["result"]
        print_info("Transaction Signature", signature)
        print_info("Transaction Explorer", EXPLORER+signature)

        time.sleep(3)
        
        new_fogo_balance = get_fogo_balance(str(owner))
        new_spl_fogo_balance = get_spl_fogo_balance(str(owner))
        print_separator()
        print_info("Updated FOGO Balance", f"{new_fogo_balance/1e9:.9f} FOGO")
        print_info("Updated SPL FOGO Balance", f"{new_spl_fogo_balance/1e9:.9f} SPL FOGO")
        
        fogo_change = (new_fogo_balance - fogo_balance) / 1e9
        spl_fogo_change = (new_spl_fogo_balance - spl_fogo_balance) / 1e9
        print_info("FOGO Change", f"{fogo_change:+.9f} FOGO")
        print_info("SPL FOGO Change", f"{spl_fogo_change:+.9f} SPL FOGO")
    else:
        print_error("Transaction failed!")
        if "error" in resp:
            print(f"Error: {resp['error']}")

def check_balances(private_key: str):
    print_header("CURRENT BALANCES")
    
    secret_bytes = base58.b58decode(private_key)
    wallet = Keypair.from_secret_key(secret_bytes)
    owner = wallet.public_key
    
    print_info("Wallet Address", str(owner))
    print_separator()
    
    fogo_balance = get_fogo_balance(str(owner))
    spl_fogo_balance = get_spl_fogo_balance(str(owner))
    
    print_info("FOGO Balance", f"{fogo_balance/1e9:.9f} FOGO")
    print_info("SPL FOGO Balance", f"{spl_fogo_balance/1e9:.9f} SPL FOGO")
    print_separator()

def show_menu():
    print_header("FOGO TOOL - Hasbi")
    print("\nSelect an Option:")
    print("  1. Wrap FOGO to SPL FOGO")
    print("  2. Unwrap SPL FOGO to FOGO")
    print("  3. Check Balances")
    print("  4. Exit")
    print_separator()

def main():
    try:
        with open('accounts.txt', 'r') as file:
            private_key = file.read().strip()

        while True:
            show_menu()
            choice = input("Enter Your Choice [1-4] -> ").strip()
            
            if choice == "1":
                amount = float(input("\nEnter Amount of FOGO to Wrap -> "))
                if amount <= 0:
                    print_error("Amount must be greater than 0")
                    continue
                wrap_fogo(private_key, amount)
                
            elif choice == "2":
                amount = float(input("\nEnter Amount of SPL FOGO to Unwrap -> "))
                if amount <= 0:
                    print_error("Amount must be greater than 0")
                    continue
                unwrap_fogo(private_key, amount)
                
            elif choice == "3":
                check_balances(private_key)
                
            elif choice == "4":
                print_header("GOODBYE!")
                break
                
            else:
                print_error("Invalid choice! Please select 1-4")
                
            if choice in ["1", "2", "3"]:
                input("\nPress Enter to continue...")
                
    except ValueError:
        print_error("Invalid input! Please enter a valid number.")
    except KeyboardInterrupt:
        print("\n\nExiting...")
    except FileNotFoundError:
        print("\n\nFile 'accounts.txt' Not Found.")
        return
    except Exception as e:
        print_error(f"An error occurred: {str(e)}")
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
