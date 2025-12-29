import boto3
import os
from dotenv import load_dotenv
import json

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# Initialize DynamoDB client
dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)
dynamodb_resource = boto3.resource('dynamodb', region_name=AWS_REGION)


def create_comments_table():
    """Create CRM_Comments table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_Comments',
            KeySchema=[
                {'AttributeName': 'comment_id', 'KeyType': 'HASH'}  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'comment_id', 'AttributeType': 'S'},
                {'AttributeName': 'post_id', 'AttributeType': 'S'},
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'PostIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'post_id', 'KeyType': 'HASH'},
                        {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                },
                {
                    'IndexName': 'UserIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                        {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_Comments table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_Comments table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_Comments table: {e}")


def create_leads_table():
    """Create CRM_Leads table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_Leads',
            KeySchema=[
                {'AttributeName': 'lead_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'lead_id', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                        {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_Leads table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_Leads table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_Leads table: {e}")


def create_posts_table():
    """Create CRM_Posts table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_Posts',
            KeySchema=[
                {'AttributeName': 'post_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'post_id', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_Posts table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_Posts table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_Posts table: {e}")


def create_templates_table():
    """Create CRM_ReplyTemplates table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_ReplyTemplates',
            KeySchema=[
                {'AttributeName': 'query_type', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'query_type', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_ReplyTemplates table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_ReplyTemplates table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_ReplyTemplates table: {e}")


def create_analytics_table():
    """Create CRM_Analytics table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_Analytics',
            KeySchema=[
                {'AttributeName': 'metric_date', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'metric_date', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_Analytics table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_Analytics table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_Analytics table: {e}")


def create_interactions_table():
    """Create CRM_UserInteractions table"""
    try:
        table = dynamodb.create_table(
            TableName='CRM_UserInteractions',
            KeySchema=[
                {'AttributeName': 'interaction_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'interaction_id', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("✅ CRM_UserInteractions table created")
        return table
    except dynamodb.exceptions.ResourceInUseException:
        print("⚠️  CRM_UserInteractions table already exists")
    except Exception as e:
        print(f"❌ Error creating CRM_UserInteractions table: {e}")


def load_reply_templates():
    """Load default reply templates into DynamoDB"""
    try:
        table = dynamodb_resource.Table('CRM_ReplyTemplates')
        
        templates = [
            {
                'query_type': 'price',
                'template_text': 'Thank you for your interest! 🙌 Our pricing varies based on your needs. Please DM us or visit www.craftingbrain.com for detailed pricing information. We offer flexible packages to suit different requirements!',
                'keywords': '["price", "cost", "how much", "pricing", "fees", "charges"]'
            },
            {
                'query_type': 'demo',
                'template_text': 'Excited to show you what we can do! 🚀 We would love to schedule a demo for you. Please DM us with your availability or visit www.craftingbrain.com to book directly. Looking forward to connecting!',
                'keywords': '["demo", "demonstration", "show me", "see how it works", "trial"]'
            },
            {
                'query_type': 'features',
                'template_text': 'Great question! 💡 We offer comprehensive features including AI-powered content generation, multi-platform posting, and advanced analytics. Check out www.craftingbrain.com for the complete feature list, or DM us for specific queries!',
                'keywords': '["features", "capabilities", "what can", "functions", "what does it do"]'
            },
            {
                'query_type': 'support',
                'template_text': 'We are here to help! 🤝 For support inquiries, please reach out via DM or contact us at www.craftingbrain.com/support. You can also call us at 9115706096. Our team is ready to assist you!',
                'keywords': '["support", "help", "issue", "problem", "assistance", "contact"]'
            },
            {
                'query_type': 'contact',
                'template_text': 'Let us connect! 📞 You can reach us at:\n📧 www.craftingbrain.com\n📱 Call: 9115706096\nOr simply DM us here, and we will get back to you shortly!',
                'keywords': '["contact", "reach out", "get in touch", "email", "phone", "call"]'
            },
            {
                'query_type': 'interested',
                'template_text': 'Thank you for your interest! 🌟 We would love to tell you more about how we can help. Please DM us or visit www.craftingbrain.com to learn more. Excited to work with you!',
                'keywords': '["interested", "want more", "tell me more", "sign up", "join", "want to know"]'
            }
        ]
        
        for template in templates:
            table.put_item(Item=template)
        
        print("✅ Reply templates loaded")
    except Exception as e:
        print(f"❌ Error loading reply templates: {e}")


def wait_for_table_creation(table_names):
    """Wait for all tables to be active"""
    import time
    
    print("\n⏳ Waiting for tables to become active...")
    
    for table_name in table_names:
        try:
            waiter = dynamodb.get_waiter('table_exists')
            waiter.wait(
                TableName=table_name,
                WaiterConfig={'Delay': 5, 'MaxAttempts': 20}
            )
            print(f"✅ {table_name} is now active")
        except Exception as e:
            print(f"⚠️  Error waiting for {table_name}: {e}")


def main():
    """Main setup function"""
    print("="*70)
    print("  🚀 Creating DynamoDB Tables for CRM System")
    print("="*70)
    print(f"\n📍 Region: {AWS_REGION}\n")
    
    # Create all tables
    create_comments_table()
    create_leads_table()
    create_posts_table()
    create_templates_table()
    create_analytics_table()
    create_interactions_table()
    
    # Wait for tables to be created
    table_names = [
        'CRM_Comments',
        'CRM_Leads',
        'CRM_Posts',
        'CRM_ReplyTemplates',
        'CRM_Analytics',
        'CRM_UserInteractions'
    ]
    
    wait_for_table_creation(table_names)
    
    # Load reply templates
    print("\n📝 Loading reply templates...")
    load_reply_templates()
    
    print("\n" + "="*70)
    print("  ✅ DynamoDB Setup Complete!")
    print("="*70)
    print("\n📊 Tables Created:")
    for table in table_names:
        print(f"   • {table}")
    
    print("\n💡 Next Steps:")
    print("   1. Update your .env file with AWS credentials")
    print("   2. Test connection: python crm_dynamodb.py")
    print("   3. Update comment_monitor.py to use CRMDynamoDB")
    print("   4. Update auto_reply.py to use CRMDynamoDB")
    print("   5. Update crm_handler.py to use CRMDynamoDB")
    print("\n")


if __name__ == "__main__":
    main()