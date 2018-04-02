# GitHub Repo Reports via AWS Lambda
Send an emailed status report for a GitHub repo via AWS Lambda. This app uses the GitHub API to fetch issue and PR status, compile a simple report, and send it off via email. 

## Requirements
##### Services
1. **AWS**: IAM profile with sufficient privileges to execute the function.
2. **SMTP server**: You can use AWS Simple Email Service (SES) if another server is unavailable.
3. **GitHub access token**: An API token that allows your Lambda function to access GitHub repo information.

##### Python
1. `requests`: This package uses `requests` to issue HTTP calls to the GitHub API. It's just much easier than `urllib`
2. `Jinja2`: A templating engine that makes email composition _way_ easier.
3. `boto3`: This is really only required if you're using KMS to encrypt your secrets (SMTP password, GitHub token, etc.) - which is recommended.

## Creating the Lambda function

## Using the Lambda function