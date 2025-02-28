# This is a simple Flask app that listens for incoming webhooks from SonarCloud and posts a comment to a GitLab merge request with the SonarCloud analysis results.
# The app extracts the project name, branch name, quality gate status, and other relevant data from the webhook payload and generates a comment based on the analysis results.
# The comment includes the project name, branch name, quality gate status, and a list of metrics that failed the quality gate.
# The app also extracts the GitLab project ID and merge request IID from the webhook payload and uses them to post a comment to the corresponding merge request.
# The app checks if an existing comment with the specified identifier already exists and updates it if necessary.
# The app runs on port 5000 and listens for incoming POST requests at the /webhook endpoint.
from flask import Flask, request, jsonify
import requests
import logging
import os

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests."""
    try:
        data = request.json
        logger.info("Received webhook payload: %s", data)

        # Check if the branch type is a pull request
        if data['branch']['type'] != 'PULL_REQUEST':
            logger.info("Ignoring non-pull request branch type")
            return jsonify({"message": "Ignoring non-pull request branch type"}), 200

        project_name = data['project']['name']
        branch_name = data['branch']['name']
        quality_gate_status = data['qualityGate']['status']
        # this is the URL to the pull request in SonarQube Cloud
        sqcloud_branch_url = data['branch']['url']

        # Get other data from SonarQube Cloud api at this point if desired

        comment = generate_comment(data, project_name, branch_name, quality_gate_status, sqcloud_branch_url)

        project_id, merge_request_iid = extract_gitlab_ids(data)
        if not project_id or not merge_request_iid:
            logger.error("Missing GitLab project ID or merge request IID")
            return jsonify({"message": "Missing GitLab project ID or merge request IID"}), 400

        token = os.getenv("GITLAB_TOKEN")
        gitlab_url = os.getenv("GITLAB_URL")
        url = f"{gitlab_url}api/v4/projects/{project_id}/merge_requests/{merge_request_iid}/notes"
        headers = {"PRIVATE-TOKEN": token}

        existing_comment_id = get_existing_comment_id(url, headers, "SonarCloud Analysis Results")
        action, response = post_or_update_comment(url, headers, comment, existing_comment_id)
        logger.info("GitLab response status: %s", response.status_code)
        logger.info("GitLab response body: %s", response.text)

        if response.status_code in [200, 201]:
            return jsonify({"message": f"Comment {action} successfully"}), response.status_code
        else:
            return jsonify({"message": f"Failed to {action} comment", "details": response.text}), response.status_code
    except Exception as e:
        logger.error("Exception occurred: %s", str(e))
        return jsonify({"message": "Exception occurred", "details": str(e)}), 500

def generate_comment(data, project_name, branch_name, quality_gate_status, sqcloud_branch_url):
    """Generate a comment based on the SonarCloud analysis results.
        
        This function only handles the default quality gate on SonarQube Cloud. If you have 
        set up a custom quality gate, you may need to modify this function to handle the
        custom conditions.
    """
    comment = "## SonarCloud Analysis Results\n"
    comment += f"### {project_name} on branch: {branch_name}\n"
    comment += f"#### Quality Gate Status: {'FAILED' if quality_gate_status == 'ERROR' else 'PASSED'}\n"

    grades = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E'}
    metric_messages = {
        'new_reliability_rating': 'Reliability Rating on New Code is worse than',
        'new_security_rating': 'Security Rating on New Code is worse than',
        'new_maintainability_rating': 'Maintainability Rating on New Code is worse than',
        'new_coverage': 'Coverage on New Code is below the threshold',
        'new_duplicated_lines_density': 'Duplication on New Code is above the threshold',
        'new_security_hotspots_reviewed': 'Security Hotspots reviewed'
    }
    operator_messages = {
        'GREATER_THAN': "above the error threshold",
        'LESS_THAN': "below the error threshold"
    }

    for condition in data['qualityGate']['conditions']:
        if condition['status'] == 'ERROR':
            metric = condition['metric']
            value = condition['value']
            error_threshold = condition['errorThreshold']
            operator = condition.get('operator', 'GREATER_THAN')
            message = operator_messages.get(operator, "unknown operator")
            descriptive_message = metric_messages.get(metric, metric)

            if metric in ['new_reliability_rating', 'new_security_rating', 'new_maintainability_rating']:
                grade = grades.get(int(value), 'Unknown')
                threshold_grade = grades.get(int(error_threshold), 'Unknown')
                comment += f"- {descriptive_message} {threshold_grade} ({grade}), which is {message} of {error_threshold}\n"
            elif metric == 'new_security_hotspots_reviewed':
                comment += f"- {value}% of {descriptive_message} ({error_threshold}% required)\n"
            else:
                comment += f"- {descriptive_message} ({value}), which is {message} of {error_threshold}\n"

    comment += f"See detailed results here: {sqcloud_branch_url}\n"
    return comment

def extract_gitlab_ids(data):
    """Extract GitLab project ID and merge request IID from the data."""
    project_id = data['properties'].get('sonar.analysis.gitlabProjectId')
    merge_request_iid = data['properties'].get('sonar.analysis.mergeRequestId')
    return project_id, merge_request_iid

def get_existing_comment_id(url, headers, comment_identifier):
    """Get the ID of an existing comment with the specified identifier."""
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error("Failed to fetch comments: %s", response.text)
        return None

    for note in response.json():
        if comment_identifier in note['body']:
            return note['id']
    return None

def post_or_update_comment(url, headers, comment, existing_comment_id):
    """Post a new comment or update an existing comment."""
    if existing_comment_id:
        update_url = f"{url}/{existing_comment_id}"
        response = requests.put(update_url, headers=headers, json={"body": comment})
        action = "updated"
    else:
        response = requests.post(url, headers=headers, json={"body": comment})
        action = "created"
    return action, response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)