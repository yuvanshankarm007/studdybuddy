#!/bin/bash
# StudyBuddy Deployment Script
# Deploys to AWS for Amazon Build Ship Shape 2026

set -e

echo "🚀 StudyBuddy Deployment Script"
echo "================================"
echo ""

# Configuration
STACK_NAME="StudyBuddy"
REGION="us-east-1"
TEMPLATE_FILE="infrastructure/cloudformation/template.yaml"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install and configure."
    exit 1
fi

echo "📋 AWS Region: $REGION"
echo "📋 Stack Name: $STACK_NAME"
echo ""

# Validate template
echo "🔍 Validating CloudFormation template..."
aws cloudformation validate-template \
    --template-body file://$TEMPLATE_FILE \
    --region $REGION

echo "✅ Template valid"
echo ""

# Deploy stack
echo "🚀 Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file $TEMPLATE_FILE \
    --stack-name $STACK_NAME \
    --region $REGION \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        ProjectName=$STACK_NAME \
    --no-fail-on-empty-changeset

echo ""
echo "✅ Deployment complete!"
echo ""

# Get outputs
echo "📊 Stack Outputs:"
aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
    --output table

echo ""
echo "🔗 Useful URLs:"
echo "  CloudWatch Dashboard: https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${STACK_NAME}-Monitoring"
echo "  DynamoDB Console: https://${REGION}.console.aws.amazon.com/dynamodbv2/home?region=${REGION}#tables"
echo ""

# Build and push Docker image (optional)
if command -v docker &> /dev/null; then
    echo "🐳 Building Docker image..."
    docker build -t studybuddy:latest .
    echo "✅ Docker image built"
fi

echo ""
echo "🏆 Ready for Amazon Build Ship Shape 2026!"
