import asyncio
import os
from datetime import datetime, timedelta
from threading import Lock
from dotenv import load_dotenv
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
import mcp.types as types
from bakong_khqr import KHQR

load_dotenv()

# Configuration
SCAN_COOLDOWN_MINUTES = int(os.environ.get('SCAN_COOLDOWN_MINUTES', 5))
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET')

# In-memory transaction storage
transactions = {}
transactions_lock = Lock()

def get_khqr_instance():
    token = os.environ.get('BAKONG_TOKEN')
    if not token:
        raise ValueError("BAKONG_TOKEN environment variable is required")
    return KHQR(token)

# Create MCP server instance
server = Server("khqr-payment-server")

@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    """List all available transactions as resources."""
    with transactions_lock:
        return [
            Resource(
                uri=f"khqr://transaction/{md5}",
                name=f"Transaction {tx['bill_number'] or md5[:8]}",
                description=f"Payment of {tx['amount']} {tx['currency']} - Status: {tx['status']}",
                mimeType="application/json",
            )
            for md5, tx in transactions.items()
        ]

@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    """Read a specific transaction resource."""
    if not uri.startswith("khqr://transaction/"):
        raise ValueError(f"Unknown resource URI: {uri}")
    
    md5 = uri.replace("khqr://transaction/", "")
    
    with transactions_lock:
        if md5 not in transactions:
            raise ValueError(f"Transaction not found: {md5}")
        
        transaction = transactions[md5]
    
    import json
    return json.dumps(transaction, indent=2)

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available KHQR payment tools."""
    return [
        Tool(
            name="generate_qr_code",
            description="Generate a KHQR payment QR code for accepting payments",
            inputSchema={
                "type": "object",
                "properties": {
                    "bank_account": {
                        "type": "string",
                        "description": "The merchant's bank account number",
                    },
                    "merchant_name": {
                        "type": "string",
                        "description": "The name of the merchant",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Payment amount (must be positive)",
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["USD", "KHR"],
                        "description": "Currency code (USD or KHR)",
                    },
                    "merchant_city": {
                        "type": "string",
                        "description": "Merchant city (default: Phnom Penh)",
                    },
                    "store_label": {
                        "type": "string",
                        "description": "Store label for identification",
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "Merchant phone number",
                    },
                    "bill_number": {
                        "type": "string",
                        "description": "Bill or invoice number",
                    },
                    "terminal_label": {
                        "type": "string",
                        "description": "Terminal identifier",
                    },
                    "static": {
                        "type": "boolean",
                        "description": "Whether to generate a static QR code",
                    },
                    "callback_url": {
                        "type": "string",
                        "description": "Callback URL for payment notifications",
                    },
                    "app_icon_url": {
                        "type": "string",
                        "description": "App icon URL for deeplink",
                    },
                    "app_name": {
                        "type": "string",
                        "description": "App name for deeplink (default: Payment)",
                    },
                    "image_format": {
                        "type": "string",
                        "enum": ["png", "jpeg", "webp", "base64", "base64_uri"],
                        "description": "Format for QR code image",
                    },
                },
                "required": ["bank_account", "merchant_name", "amount", "currency"],
            },
        ),
        Tool(
            name="check_payment_status",
            description="Check the payment status of a transaction by MD5 hash",
            inputSchema={
                "type": "object",
                "properties": {
                    "md5": {
                        "type": "string",
                        "description": "The MD5 hash of the transaction to check",
                    },
                },
                "required": ["md5"],
            },
        ),
        Tool(
            name="get_transaction",
            description="Get detailed information about a transaction",
            inputSchema={
                "type": "object",
                "properties": {
                    "md5": {
                        "type": "string",
                        "description": "The MD5 hash of the transaction",
                    },
                },
                "required": ["md5"],
            },
        ),
        Tool(
            name="list_transactions",
            description="List all transactions with optional filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "paid", "all"],
                        "description": "Filter by transaction status (default: all)",
                    },
                },
            },
        ),
        Tool(
            name="simulate_payment_callback",
            description="Simulate a payment callback (for testing purposes)",
            inputSchema={
                "type": "object",
                "properties": {
                    "md5": {
                        "type": "string",
                        "description": "The MD5 hash of the transaction",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["success", "0"],
                        "description": "Payment status (success or 0)",
                    },
                },
                "required": ["md5"],
            },
        ),
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    
    if name == "generate_qr_code":
        try:
            khqr = get_khqr_instance()
            
            # Validate required fields
            required = ['bank_account', 'merchant_name', 'amount', 'currency']
            for field in required:
                if field not in arguments:
                    return [TextContent(
                        type="text",
                        text=f"Error: Missing required field: {field}"
                    )]
            
            # Validate amount
            if not isinstance(arguments['amount'], (int, float)) or arguments['amount'] <= 0:
                return [TextContent(
                    type="text",
                    text="Error: Amount must be a positive number"
                )]
            
            # Validate currency
            if arguments['currency'] not in ['USD', 'KHR']:
                return [TextContent(
                    type="text",
                    text="Error: Currency must be USD or KHR"
                )]
            
            # Create QR code
            qr_code = khqr.create_qr(
                bank_account=arguments['bank_account'],
                merchant_name=arguments['merchant_name'],
                merchant_city=arguments.get('merchant_city', 'Phnom Penh'),
                amount=arguments['amount'],
                currency=arguments['currency'],
                store_label=arguments.get('store_label', ''),
                phone_number=arguments.get('phone_number', ''),
                bill_number=arguments.get('bill_number', ''),
                terminal_label=arguments.get('terminal_label', ''),
                static=arguments.get('static', False)
            )
            
            md5_hash = khqr.generate_md5(qr_code)
            
            # Generate deeplink if callback provided
            deeplink = None
            if 'callback_url' in arguments:
                deeplink = khqr.generate_deeplink(
                    qr=qr_code,
                    callback=arguments['callback_url'],
                    appIconUrl=arguments.get('app_icon_url', ''),
                    appName=arguments.get('app_name', 'Payment')
                )
            
            # Store transaction
            with transactions_lock:
                transactions[md5_hash] = {
                    'qr_code': qr_code,
                    'md5': md5_hash,
                    'amount': arguments['amount'],
                    'currency': arguments['currency'],
                    'merchant_name': arguments['merchant_name'],
                    'bill_number': arguments.get('bill_number', ''),
                    'status': 'pending',
                    'scanned': False,
                    'paid': False,
                    'created_at': datetime.now().isoformat(),
                    'last_scan_time': None,
                    'payment_time': None,
                    'scan_count': 0
                }
            
            result = {
                'success': True,
                'qr_code': qr_code,
                'md5': md5_hash,
                'amount': arguments['amount'],
                'currency': arguments['currency'],
                'status': 'pending',
                'resource_uri': f"khqr://transaction/{md5_hash}"
            }
            
            if deeplink:
                result['deeplink'] = deeplink
            
            # Handle image format if requested
            response_parts = [TextContent(
                type="text",
                text=f"QR Code Generated Successfully!\n\nMD5: {md5_hash}\nAmount: {arguments['amount']} {arguments['currency']}\nStatus: pending\n\nQR Code Data: {qr_code}"
            )]
            
            if 'image_format' in arguments:
                img_format = arguments['image_format']
                qr_image = khqr.qr_image(qr_code, format=img_format)
                
                if img_format in ['base64', 'base64_uri']:
                    response_parts.append(TextContent(
                        type="text",
                        text=f"\nQR Code Image ({img_format}):\n{qr_image}"
                    ))
            
            return response_parts
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error generating QR code: {str(e)}"
            )]
    
    elif name == "check_payment_status":
        try:
            md5 = arguments['md5']
            
            with transactions_lock:
                if md5 not in transactions:
                    return [TextContent(
                        type="text",
                        text=f"Error: Transaction not found: {md5}"
                    )]
                
                transaction = transactions[md5]
            
            khqr = get_khqr_instance()
            payment_status = khqr.check_payment(md5)
            
            # Update transaction status
            with transactions_lock:
                if payment_status == 'PAID':
                    transactions[md5]['status'] = 'paid'
                    transactions[md5]['paid'] = True
                    if not transactions[md5]['payment_time']:
                        transactions[md5]['payment_time'] = datetime.now().isoformat()
                
                transaction = transactions[md5]
            
            result = f"""Payment Status Check:

MD5: {md5}
Status: {transaction['status']}
Paid: {transaction['paid']}
Scanned: {transaction['scanned']}
Amount: {transaction['amount']} {transaction['currency']}
Created: {transaction['created_at']}
Payment Time: {transaction['payment_time'] or 'N/A'}
Scan Count: {transaction['scan_count']}
API Payment Status: {payment_status}"""
            
            return [TextContent(type="text", text=result)]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error checking payment status: {str(e)}"
            )]
    
    elif name == "get_transaction":
        md5 = arguments['md5']
        
        with transactions_lock:
            if md5 not in transactions:
                return [TextContent(
                    type="text",
                    text=f"Error: Transaction not found: {md5}"
                )]
            
            transaction = transactions[md5]
        
        import json
        return [TextContent(
            type="text",
            text=json.dumps(transaction, indent=2)
        )]
    
    elif name == "list_transactions":
        status_filter = arguments.get('status', 'all')
        
        with transactions_lock:
            filtered_txs = transactions.copy()
            
            if status_filter != 'all':
                filtered_txs = {
                    k: v for k, v in filtered_txs.items()
                    if v['status'] == status_filter
                }
        
        if not filtered_txs:
            return [TextContent(
                type="text",
                text=f"No transactions found with status: {status_filter}"
            )]
        
        result = f"Transactions (Status: {status_filter}):\n\n"
        for md5, tx in filtered_txs.items():
            result += f"- MD5: {md5[:16]}...\n"
            result += f"  Amount: {tx['amount']} {tx['currency']}\n"
            result += f"  Status: {tx['status']}\n"
            result += f"  Bill: {tx['bill_number'] or 'N/A'}\n"
            result += f"  Created: {tx['created_at']}\n\n"
        
        return [TextContent(type="text", text=result)]
    
    elif name == "simulate_payment_callback":
        md5 = arguments['md5']
        payment_status = arguments.get('status', 'success')
        
        with transactions_lock:
            if md5 not in transactions:
                return [TextContent(
                    type="text",
                    text=f"Error: Transaction not found: {md5}"
                )]
            
            transaction = transactions[md5]
            
            if transaction['paid']:
                return [TextContent(
                    type="text",
                    text="Payment already processed"
                )]
            
            # Check cooldown
            last_scan_time = transaction['last_scan_time']
            if last_scan_time:
                last_scan_dt = datetime.fromisoformat(last_scan_time)
                cooldown_end = last_scan_dt + timedelta(minutes=SCAN_COOLDOWN_MINUTES)
                
                if datetime.now() < cooldown_end:
                    remaining = (cooldown_end - datetime.now()).total_seconds()
                    return [TextContent(
                        type="text",
                        text=f"QR code is in cooldown. Wait {int(remaining)} seconds."
                    )]
            
            # Update transaction
            transactions[md5]['scanned'] = True
            transactions[md5]['last_scan_time'] = datetime.now().isoformat()
            transactions[md5]['scan_count'] += 1
            
            if payment_status in ['success', '0']:
                transactions[md5]['status'] = 'paid'
                transactions[md5]['paid'] = True
                transactions[md5]['payment_time'] = datetime.now().isoformat()
        
        return [TextContent(
            type="text",
            text=f"Payment callback simulated successfully. Status: {transactions[md5]['status']}"
        )]
    
    else:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]

async def main():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="khqr-payment-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())