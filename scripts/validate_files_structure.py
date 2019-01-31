"""
This script is used to validate the files in Content repository. Specifically for each file:
1) Proper prefix
2) Proper suffix
3) Valid yml/json schema
4) Having ReleaseNotes if applicable.

It can be run to check only commited changes (if the first argument is 'true') or all the files in the repo.
Note - if it is run for all the files in the repo it won't check releaseNotes, use `setContentDescriptor.sh`
for that task.
"""
import glob
import sys
try:
    import yaml
except ImportError:
    print "Please install pyyaml, you can do it by running: `pip install pyyaml`"
    sys.exit(1)
try:
    from pykwalify.core import Core
except ImportError:
    print "Please install pykwalify, you can do it by running: `pip install -I pykwalify`"
    sys.exit(1)

import re
import os
import json
import io
import math
import string
import argparse
from subprocess import Popen, PIPE
from distutils.version import LooseVersion

from update_id_set import get_script_data, get_playbook_data, get_integration_data, get_script_package_data

# Magic Numbers
IMAGE_MAX_SIZE = 10 * 1024  # 10kB

# dirs
INTEGRATIONS_DIR = "Integrations"
SCRIPTS_DIR = "Scripts"
PLAYBOOKS_DIR = "Playbooks"
TEST_PLAYBOOKS_DIR = "TestPlaybooks"
REPORTS_DIR = "Reports"
DASHBOARDS_DIR = "Dashboards"
WIDGETS_DIR = "Widgets"
INCIDENT_FIELDS_DIR = "IncidentFields"
LAYOUTS_DIR = "Layouts"
CLASSIFIERS_DIR = "Classifiers"
MISC_DIR = "Misc"
CONNECTIONS_DIR = "Connections"

# file types regexes
IMAGE_REGEX = ".*.png"
SCRIPT_YML_REGEX = "{}.*.yml".format(SCRIPTS_DIR)
SCRIPT_PY_REGEX = "{}.*.py".format(SCRIPTS_DIR)
SCRIPT_JS_REGEX = "{}.*.js".format(SCRIPTS_DIR)
INTEGRATION_YML_REGEX = "{}.*.yml".format(INTEGRATIONS_DIR)
INTEGRATION_REGEX = "{}.*integration-.*.yml".format(INTEGRATIONS_DIR)
PLAYBOOK_REGEX = "{}.*playbook-.*.yml".format(PLAYBOOKS_DIR)
TEST_SCRIPT_REGEX = "{}.*script-.*.yml".format(TEST_PLAYBOOKS_DIR)
TEST_PLAYBOOK_REGEX = "{}.*playbook-.*.yml".format(TEST_PLAYBOOKS_DIR)
SCRIPT_REGEX = "{}.*script-.*.yml".format(SCRIPTS_DIR)
WIDGETS_REGEX = "{}.*widget-.*.json".format(WIDGETS_DIR)
DASHBOARD_REGEX = "{}.*dashboard-.*.json".format(DASHBOARDS_DIR)
CONNECTIONS_REGEX = "{}.*canvas-context-connections.*.json".format(CONNECTIONS_DIR)
CLASSIFIER_REGEX = "{}.*classifier-.*.json".format(CLASSIFIERS_DIR)
LAYOUT_REGEX = "{}.*layout-.*.json".format(LAYOUTS_DIR)
INCIDENT_FIELDS_REGEX = "{}.*incidentfields.*.json".format(INCIDENT_FIELDS_DIR)
INCIDENT_FIELD_REGEX = "{}.*incidentfield-.*.json".format(INCIDENT_FIELDS_DIR)
MISC_REGEX = "{}.*reputations.*.json".format(MISC_DIR)
REPORT_REGEX = "{}.*report-.*.json".format(REPORTS_DIR)

CHECKED_TYPES_REGEXES = [INTEGRATION_REGEX, PLAYBOOK_REGEX, SCRIPT_REGEX, INTEGRATION_YML_REGEX,
                         WIDGETS_REGEX, DASHBOARD_REGEX, CONNECTIONS_REGEX, CLASSIFIER_REGEX, SCRIPT_YML_REGEX,
                         LAYOUT_REGEX, INCIDENT_FIELDS_REGEX, INCIDENT_FIELD_REGEX, MISC_REGEX, REPORT_REGEX]

SKIPPED_SCHEMAS = [MISC_REGEX, REPORT_REGEX]

KNOWN_FILE_STATUSES = ['a', 'm', 'd']

REGEXES_TO_SCHEMA_DIC = {
    INTEGRATION_REGEX: "integration",
    INTEGRATION_YML_REGEX: "integration",
    PLAYBOOK_REGEX: "playbook",
    TEST_PLAYBOOK_REGEX: "test-playbook",
    SCRIPT_REGEX: "script",
    WIDGETS_REGEX: "widget",
    DASHBOARD_REGEX: "dashboard",
    CONNECTIONS_REGEX: "canvas-context-connections",
    CLASSIFIER_REGEX: "classifier",
    LAYOUT_REGEX: "layout",
    INCIDENT_FIELDS_REGEX: "incidentfields",
    INCIDENT_FIELD_REGEX: "incidentfield"
}

SCHEMAS_PATH = "Tests/schemas/"

DIRS = [INTEGRATIONS_DIR, SCRIPTS_DIR, PLAYBOOKS_DIR, REPORTS_DIR, DASHBOARDS_DIR, WIDGETS_DIR, INCIDENT_FIELDS_DIR,
        LAYOUTS_DIR, CLASSIFIERS_DIR, MISC_DIR]

# secrets settings
# Entropy score is determined by shanon's entropy algorithm, most English words will score between 1.5 and 3.5
ENTROPY_THRESHOLD = 3.8
SECRETS_WHITE_LIST_FILE = 'secrets_white_list'


class LOG_COLORS:
    NATIVE = '\033[m'
    RED = '\033[01;31m'
    GREEN = '\033[01;32m'


# print srt in the given color
def print_color(msg, color):
    print(str(color) + str(msg) + LOG_COLORS.NATIVE)


def print_error(error_str):
    print_color(error_str, LOG_COLORS.RED)


def run_git_command(command):
    p = Popen(command.split(), stdout=PIPE, stderr=PIPE)
    output, err = p.communicate()
    if err:
        print_error("Failed to run git command " + command)
        sys.exit(1)
    return output


def checked_type(file_path):
    for regex in CHECKED_TYPES_REGEXES:
        if re.match(regex, file_path, re.IGNORECASE):
            return True
    return False


def get_modified_files(files_string):
    all_files = files_string.split('\n')
    added_files_list = set([])
    modified_files_list = set([])
    for f in all_files:
        file_data = f.split()
        if not file_data:
            continue

        file_status = file_data[0]
        file_path = file_data[1]

        if file_path.endswith('.js') or file_path.endswith('.py'):
            continue
        if file_status.lower() == 'm' and checked_type(file_path) and not file_path.startswith('.'):
            modified_files_list.add(file_path)
        elif file_status.lower() == 'a' and checked_type(file_path) and not file_path.startswith('.'):
            added_files_list.add(file_path)
        elif file_status.lower() not in KNOWN_FILE_STATUSES:
            print_error(file_path + " file status is an unknown known one, "
                                    "please check. File status was: " + file_status)

    return modified_files_list, added_files_list


def validate_file_release_notes(file_path):
    data_dictionary = None
    if re.match(TEST_PLAYBOOK_REGEX, file_path, re.IGNORECASE):
        return True  # Test playbooks don't need releaseNotes

    if os.path.isfile(file_path):
        with open(os.path.expanduser(file_path), "r") as f:
            if file_path.endswith(".json"):
                data_dictionary = json.load(f)
            elif file_path.endswith(".yaml") or file_path.endswith('.yml'):
                try:
                    data_dictionary = yaml.safe_load(f)
                except Exception as e:
                    print_error(file_path + " has yml structure issue. Error was: " + str(e))
                    return False

        if data_dictionary and data_dictionary.get('releaseNotes') is None:
            print_error("File " + file_path + " is missing releaseNotes, please add.")
            return False

    return True


def validate_schema(file_path, matching_regex=None):
    if matching_regex is None:
        for regex in CHECKED_TYPES_REGEXES:
            if re.match(regex, file_path, re.IGNORECASE):
                matching_regex = regex
                break

    if matching_regex in SKIPPED_SCHEMAS:
        return True

    if not os.path.isfile(file_path):
        return True

    if matching_regex is not None and REGEXES_TO_SCHEMA_DIC.get(matching_regex):
        c = Core(source_file=file_path,
                 schema_files=[SCHEMAS_PATH + REGEXES_TO_SCHEMA_DIC.get(matching_regex) + '.yml'])
        try:
            c.validate(raise_exception=True)
            return True
        except Exception as err:
            print_error('Failed: %s failed' % (file_path,))
            print_error(err)
            return False

    print file_path + " doesn't match any of the known supported file prefix/suffix," \
                      " please make sure that its naming is correct."
    return True


def is_release_branch():
    diff_string_config_yml = run_git_command("git diff origin/master .circleci/config.yml")
    if re.search('[+-][ ]+CONTENT_VERSION: ".*', diff_string_config_yml):
        return True

    return False


def changed_id(file_path):
    change_string = run_git_command("git diff HEAD {}".format(file_path))
    if re.search("[+-](  )?id: .*", change_string):
        print_error("You've changed the ID of the file {0} please undo.".format(file_path))
        return True

    return False


def is_added_required_fields(file_path):
    change_string = run_git_command("git diff HEAD {0}".format(file_path))
    if re.search("\+  name: .*\n.*\n.*\n   required: true", change_string) or \
            re.search("\+[ ]+required: true", change_string):
        print_error("You've added required fields in the integration file {}".format(file_path))
        return True

    return False


def get_script_or_integration_id(file_path):
    data_dictionary = get_json(file_path)

    if data_dictionary:
        commonfields = data_dictionary.get('commonfields', {})
        return commonfields.get('id', ['-', ])


def get_json(file_path):
    data_dictionary = None
    with open(os.path.expanduser(file_path), "r") as f:
        if file_path.endswith(".yaml") or file_path.endswith('.yml'):
            try:
                data_dictionary = yaml.safe_load(f)
            except Exception as e:
                print_error(file_path + " has yml structure issue. Error was: " + str(e))
                return []

    if type(data_dictionary) is dict:
        return data_dictionary
    else:
        return {}


def collect_ids(file_path):
    """Collect id mentioned in file_path"""
    data_dictionary = get_json(file_path)

    if data_dictionary:
        return data_dictionary.get('id', '-')


def is_test_in_conf_json(file_path):
    file_id = collect_ids(file_path)

    with open("./Tests/conf.json") as data_file:
        conf = json.load(data_file)

    conf_tests = conf['tests']
    for test in conf_tests:
        playbook_id = test['playbookID']
        if file_id == playbook_id:
            return True

    print_error("You've failed to add the {0} to conf.json".format(file_path))
    return False


def oversize_image(file_path):
    if re.match(IMAGE_REGEX, file_path, re.IGNORECASE):
        if os.path.getsize(file_path) > IMAGE_MAX_SIZE:
            print_error("{} has too large logo, please update the logo to be under 10kB".format(file_path))
            return True

        return False

    data_dictionary = get_json(file_path)
    image = data_dictionary.get('image', '')
    if image == '':
        return False

    if ((len(image) - 22) / 4.0) * 3 > IMAGE_MAX_SIZE:
        print_error("{} has too large logo, please update the logo to be under 10kB".format(file_path))
        return True

    return False


def is_existing_image(file_path):
    is_image_in_yml = False
    is_image_in_package = False
    if get_json(file_path).get('image'):
        is_image_in_yml = True

    if not re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE):
        package_path = os.path.dirname(file_path)
        image_path = glob.glob(package_path + '/*.png')
        if image_path:
            if is_image_in_yml:
                print_error("You have added an image both in the package and in the yml "
                            "file, please update the package {}".format(package_path))
                return False

            is_image_in_package = True

    if not(is_image_in_package or is_image_in_yml):
        print_error("You have failed to add an image in the yml/package for {}".format(file_path))

    return is_image_in_package or is_image_in_yml


def get_modified_and_added_files(branch_name, is_circle):
    all_changed_files_string = run_git_command("git diff --name-status origin/master...{}".format(branch_name))

    if is_circle:
        modified_files, added_files = get_modified_files(all_changed_files_string)

    else:
        files_string = run_git_command("git diff --name-status --no-merges HEAD")

        modified_files, added_files = get_modified_files(files_string)
        _, added_files_from_branch = get_modified_files(all_changed_files_string)
        for mod_file in modified_files:
            if mod_file in added_files_from_branch:
                added_files.add(mod_file)
                modified_files = modified_files - set([mod_file])

    return modified_files, added_files


def get_from_version(file_path):
    data_dictionary = get_json(file_path)

    if data_dictionary:
        return data_dictionary.get('fromversion', '0.0.0')


def get_to_version(file_path):
    data_dictionary = get_json(file_path)

    if data_dictionary:
        return data_dictionary.get('toversion', '99.99.99')


def changed_command_name_or_arg(file_path):
    change_string = run_git_command("git diff HEAD {0}".format(file_path))
    deleted_groups = re.search("-([ ]+)?- name: (.*)", change_string)
    added_groups = re.search("\+([ ]+)?- name: (.*)", change_string)
    if deleted_groups and (not added_groups or (added_groups and deleted_groups.group(2) != added_groups.group(2))):
        print_error("Possible backwards compatibility break, You've changed the name of a command or its arg in"
                    " the file {0} please undo, the line was:\n{1}".format(file_path, deleted_groups.group(0)[1:]))
        return True

    return False


def changed_docker_image(file_path):
    change_string = run_git_command("git diff HEAD {0}".format(file_path))
    is_docker_added = re.search("\+([ ]+)?dockerimage: .*", change_string)
    is_docker_deleted = re.search("-([ ]+)?dockerimage: .*", change_string)
    if is_docker_added or is_docker_deleted:
        print_error("Possible backwards compatibility break, You've changed the docker for the file {}"
                    " this is not allowed.".format(file_path))
        return True

    return False


def validate_version(file_path):
    change_string = run_git_command("git diff HEAD {0}".format(file_path))
    is_incorrect_version = re.search("\+([ ]+)?version: (!-1)", change_string)
    is_incorrect_version_secondary = re.search("\+([ ]+)?\"version\": (!-1)", change_string)

    if is_incorrect_version or is_incorrect_version_secondary:
        print_error("The version for our files should always be -1, please update the file {}.".format(file_path))
        return True

    return False


def validate_fromversion_on_modified(file_path):
    change_string = run_git_command("git diff HEAD {0}".format(file_path))
    is_added_from_version = re.search("\+([ ]+)?fromversion: .*", change_string)
    is_added_from_version_secondary = re.search("\+([ ]+)?\"fromVersion\": .*", change_string)

    if is_added_from_version or is_added_from_version_secondary:
        print_error("You've added fromversion to an existing file in the system, this is not allowed, please undo. "
                    "the file was {}.".format(file_path))
        return True

    return False


def changed_context(file_path):
    with open(file_path, 'r') as file_data:
        change_string = file_data.read()

    deleted_groups = re.search("-([ ]+)?- contextPath: (.*)", change_string)
    added_groups = re.search("\+([ ]+)?- contextPath: (.*)", change_string)
    if deleted_groups and (not added_groups or (added_groups and deleted_groups.group(2) != added_groups.group(2))):
        print_error("Possible backwards compatibility break, You've changed the context in the file {0} please "
                    "undo, the line was:\n{1}".format(file_path, deleted_groups.group(0)[1:]))
        return True

    return False


def is_valid_in_id_set(file_path, obj_data, obj_set):
    is_found = False
    file_id = obj_data.keys()[0]

    for checked_instance in obj_set:
        checked_instance_id = checked_instance.keys()[0]
        checked_instance_data = checked_instance[checked_instance_id]
        checked_instance_toversion = checked_instance_data.get('toversion', '99.99.99')
        checked_instance_fromversion = checked_instance_data.get('fromversion', '0.0.0')
        obj_to_version = obj_data[file_id].get('toversion', '99.99.99')
        obj_from_version = obj_data[file_id].get('fromversion', '0.0.0')
        if checked_instance_id == file_id and checked_instance_toversion == obj_to_version and \
                checked_instance_fromversion == obj_from_version:
            is_found = True
            if checked_instance_data != obj_data[file_id]:
                print_error("You have failed to update id_set.json with the data of {} "
                            "please run `python Tests/scripts/update_id_set.py`".format(file_path))
                return False

    if not is_found:
        print_error("You have failed to update id_set.json with the data of {} "
                    "please run `python Tests/scripts/update_id_set.py`".format(file_path))

    return is_found


def playbook_valid_in_id_set(file_path, playbook_set):
    playbook_data = get_playbook_data(file_path)
    return is_valid_in_id_set(file_path, playbook_data, playbook_set)


def script_valid_in_id_set(file_path, script_set, script_data=None):
    if script_data is None:
        script_data = get_script_data(file_path)

    return is_valid_in_id_set(file_path, script_data, script_set)


def integration_valid_in_id_set(file_path, integration_set):
    integration_data = get_integration_data(file_path)
    return is_valid_in_id_set(file_path, integration_data, integration_set)


def validate_committed_files(branch_name, is_circle):

    # Get all files that have been modified & added to repo
    secrets_file_paths = get_all_diff_text_files(branch_name, is_circle)
    secrets_found = search_potential_secrets(secrets_file_paths)

    if secrets_found:
        print_error('Secrets were found in the following files:\n')
        for file_name in secrets_found:
            print_error('\nFile Name: ' + file_name)
            print_error(json.dumps(secrets_found[file_name], indent=4))
        if not is_circle:
            print_error('Remove or whitelist secrets in order to proceed, then re-commit\n')
        else:
            print_error('The secrets were exposed in public repository, remove the files asap and report it.\n')

        sys.exit(1)

    modified_files, added_files = get_modified_and_added_files(branch_name, is_circle)
    with open('./Tests/id_set.json', 'r') as id_set_file:
        id_set = json.load(id_set_file)

    script_set = id_set['scripts']
    playbook_set = id_set['playbooks']
    integration_set = id_set['integrations']
    test_playbook_set = id_set['TestPlaybooks']

    has_schema_problem = validate_modified_files(integration_set, modified_files,
                                                 playbook_set, script_set, test_playbook_set, is_circle)

    has_schema_problem = validate_added_files(added_files, integration_set, playbook_set,
                                              script_set, test_playbook_set, is_circle) or has_schema_problem

    if has_schema_problem:
        sys.exit(1)


def is_valid_id(objects_set, compared_id, file_path, compared_obj_data=None):
    if compared_obj_data is None:
        from_version = get_from_version(file_path)

    else:
        value = compared_obj_data.values()[0]
        from_version = value.get('fromversion', '0.0.0')

    data_dict = get_json(file_path)
    if data_dict.get('name') != compared_id:
        print_error("The ID is not equal to the name, the convetion is for them to be identical, please fix that,"
                    " the file is {}".format(file_path))
        return False

    for obj in objects_set:
        obj_id = obj.keys()[0]
        obj_data = obj.values()[0]
        if obj_id == compared_id:
            if LooseVersion(from_version) <= LooseVersion(obj_data.get('toversion', '99.99.99')):
                print_error("The ID {0} already exists, please update the file {1} or update the "
                            "id_set.json toversion field of this id to match the "
                            "old occurrence of this id".format(compared_id, file_path))
                return False

    return True


def validate_added_files(added_files, integration_set, playbook_set, script_set, test_playbook_set, is_circle):
    has_schema_problem = False
    for file_path in added_files:
        print "Validating {}".format(file_path)
        if not validate_schema(file_path):
            has_schema_problem = True

        if re.match(TEST_PLAYBOOK_REGEX, file_path, re.IGNORECASE):
            if not is_test_in_conf_json(file_path) or \
                    (is_circle and not playbook_valid_in_id_set(file_path, test_playbook_set)):
                has_schema_problem = True

            if not is_circle and not is_valid_id(test_playbook_set, collect_ids(file_path), file_path):
                has_schema_problem = True

        elif re.match(SCRIPT_REGEX, file_path, re.IGNORECASE) or re.match(TEST_SCRIPT_REGEX, file_path, re.IGNORECASE):
            if is_circle and not script_valid_in_id_set(file_path, script_set):
                has_schema_problem = True

            if not is_circle and not is_valid_id(script_set, get_script_or_integration_id(file_path), file_path):
                has_schema_problem = True

        elif re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                re.match(INTEGRATION_YML_REGEX, file_path, re.IGNORECASE):
            if oversize_image(file_path) or not is_existing_image(file_path):
                has_schema_problem = True

            if is_circle and not integration_valid_in_id_set(file_path, integration_set):
                has_schema_problem = True

            if not is_circle and not is_valid_id(integration_set, get_script_or_integration_id(file_path), file_path):
                has_schema_problem = True

        elif re.match(PLAYBOOK_REGEX, file_path, re.IGNORECASE):
            if is_circle and not playbook_valid_in_id_set(file_path, playbook_set):
                has_schema_problem = True

            if not is_circle and not is_valid_id(playbook_set, collect_ids(file_path), file_path):
                has_schema_problem = True

        elif re.match(IMAGE_REGEX, file_path, re.IGNORECASE):
            if oversize_image(file_path):
                has_schema_problem = True

        elif re.match(SCRIPT_YML_REGEX, file_path, re.IGNORECASE) or \
                re.match(SCRIPT_PY_REGEX, file_path, re.IGNORECASE) or \
                re.match(SCRIPT_JS_REGEX, file_path, re.IGNORECASE):
            yml_path, code = get_script_package_data(os.path.dirname(file_path))
            script_data = get_script_data(yml_path, script_code=code)

            if is_circle and not script_valid_in_id_set(yml_path, script_set, script_data):
                has_schema_problem = True

            if not is_circle and not is_valid_id(script_set, get_script_or_integration_id(yml_path),
                                                 yml_path, script_data):
                has_schema_problem = True

    return has_schema_problem


def validate_modified_files(integration_set, modified_files, playbook_set, script_set, test_playbook_set, is_circle):
    has_schema_problem = False
    for file_path in modified_files:
        print "Validating {}".format(file_path)
        if not validate_schema(file_path) or changed_id(file_path) or validate_version(file_path) or \
                validate_fromversion_on_modified(file_path):
            has_schema_problem = True
        if not is_release_branch() and not validate_file_release_notes(file_path):
            has_schema_problem = True

        if re.match(PLAYBOOK_REGEX, file_path, re.IGNORECASE):
            if is_circle and not playbook_valid_in_id_set(file_path, playbook_set):
                has_schema_problem = True

        elif re.match(TEST_PLAYBOOK_REGEX, file_path, re.IGNORECASE):
            if is_circle and not playbook_valid_in_id_set(file_path, test_playbook_set):
                has_schema_problem = True

        elif re.match(TEST_SCRIPT_REGEX, file_path, re.IGNORECASE):
            if is_circle and not script_valid_in_id_set(file_path, script_set):
                has_schema_problem = True

        elif re.match(SCRIPT_REGEX, file_path, re.IGNORECASE):
            if changed_command_name_or_arg(file_path) or changed_context(file_path) or \
                    (is_circle and not script_valid_in_id_set(file_path, script_set)) or \
                    changed_docker_image(file_path):
                has_schema_problem = True

        elif re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                re.match(INTEGRATION_YML_REGEX, file_path, re.IGNORECASE):
            if oversize_image(file_path) or is_added_required_fields(file_path) or \
                    changed_command_name_or_arg(file_path) or changed_context(file_path) or \
                    (is_circle and not integration_valid_in_id_set(file_path, integration_set)) or \
                    changed_docker_image(file_path) or not is_existing_image(file_path):
                has_schema_problem = True

        elif re.match(IMAGE_REGEX, file_path, re.IGNORECASE):
            if oversize_image(file_path):
                has_schema_problem = True

        elif re.match(SCRIPT_YML_REGEX, file_path, re.IGNORECASE) or \
                re.match(SCRIPT_PY_REGEX, file_path, re.IGNORECASE) or \
                re.match(SCRIPT_JS_REGEX, file_path, re.IGNORECASE):
            yml_path, code = get_script_package_data(os.path.dirname(file_path))
            script_data = get_script_data(yml_path, script_code=code)

            if changed_command_name_or_arg(yml_path) or changed_context(yml_path) or \
                    (is_circle and not script_valid_in_id_set(yml_path, script_set, script_data)):
                has_schema_problem = True

    return has_schema_problem


def validate_all_files():
    wrong_schema = False

    for regex in CHECKED_TYPES_REGEXES:
        splitted_regex = regex.split(".*")
        directory = splitted_regex[0]
        for root, dirs, files in os.walk(directory):
            print_color("Validating {} directory:".format(directory), LOG_COLORS.GREEN)
            for file_name in files:
                file_path = os.path.join(root, file_name)
                # skipping hidden files
                if file_name.startswith('.'):
                    continue
                print "Validating " + file_name
                if not validate_schema(file_path):
                    print_error("file " + file_path + " schema is wrong.")
                    wrong_schema = True

    if wrong_schema:
        sys.exit(1)


def validate_conf_json():
    with open("./Tests/conf.json") as data_file:
        conf = json.load(data_file)

    skipped_tests_conf = conf['skipped_tests']
    skipped_integrations_conf = conf['skipped_integrations']

    problemtic_tests = []
    problemtic_integrations = []

    for test, description in skipped_tests_conf.items():
        if description == "":
            problemtic_tests.append(test)

    for integration, description in skipped_integrations_conf.items():
        if description == "":
            problemtic_integrations.append(integration)

    if problemtic_tests:
        print("Those tests don't have description:\n{0}".format('\n'.join(problemtic_tests)))

    if problemtic_integrations:
        print("Those integrations don't have description:\n{0}".format('\n'.join(problemtic_integrations)))

    if problemtic_integrations or problemtic_tests:
        sys.exit(1)


def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def is_text_file(file_path):
    file_extension = os.path.splitext(file_path)[1]
    text_file_types = {'.yml', '.py', '.json', '.md', '.txt', '.sh', '.ini', '.eml', '', '.csv'}
    if file_extension in text_file_types:
        return True
    return False


def get_diff_text_files(files_string):
    """Filter out only added/modified text files from git diff
    :param files_string: string representing the git diff files
    :return: text_files_list: string of full path to text files
    """
    # file statuses to filter from the diff, no need to test deleted files.
    accepted_file_statuses = ['M', 'A']
    all_files = files_string.split('\n')
    text_files_list = set()
    for file_name in all_files:
        file_data = file_name.split()
        if not file_data:
            continue

        file_status = file_data[0]
        file_path = file_data[1]
        # only modified/added file, text readable, exclude white_list file
        if file_status.upper() in accepted_file_statuses and is_text_file(file_path) \
                and SECRETS_WHITE_LIST_FILE not in file_path:
            text_files_list.add(file_path)

    return text_files_list


def get_all_diff_text_files(branch_name, is_circle):
    """
    :param branch_name: current branch being worked on
    :param is_circle: boolean to check if being ran from circle
    :return:
    """
    if is_circle:
        branch_changed_files_string = run_git_command("git diff --name-status origin/master...{}".format(branch_name))
        text_files_list = get_diff_text_files(branch_changed_files_string)

    else:
        local_changed_files_string = run_git_command("git diff --name-status --no-merges HEAD")
        text_files_list = get_diff_text_files(local_changed_files_string)

    return text_files_list


def search_potential_secrets(secrets_file_paths):
    """Returns potential secrets(sensitive data) found in committed and added files
    :param secrets_file_paths: paths of files that are being commited to git repo
    :return: dictionary of strings sorted by file name for secrets found in files
    """
    # Get generic white list set
    with io.open('./Tests/secrets_white_list.json', mode="r", encoding="utf-8") as secrets_white_list_file:
        secrets_white_list = set(json.load(secrets_white_list_file))

    secrets_found = {}

    for file_path in secrets_file_paths:
        file_name = file_path.split('/')[-1]
        high_entropy_strings = []
        regex_secrets = []

        # if py file, search for yml in order to retrieve temp white list
        file_path_temp, file_extension = os.path.splitext(file_path)
        if file_extension == '.py':
            yml_file_contents = retrieve_related_yml(file_path_temp)

        # Open each file, read its contents in UTF-8 encoding to avoid unicode characters
        with io.open('./' + file_path, mode="r", encoding="utf-8") as file:
            file_contents = file.read()

            # Add all context output paths keywords to whitelist temporary
            temp_white_list = create_temp_white_list(yml_file_contents if yml_file_contents else file_contents)
            secrets_white_list = secrets_white_list.union(temp_white_list)

            # Search by lines after strings with high entropy as possibly suspicious
            for line in set(file_contents.split('\n')):

                # if detected disable-secrets comment, skip the line
                if bool(re.findall(r'(disable-secrets-detection)', line)):
                    file_contents = file_contents.replace(line, '')
                    continue

                # REGEX scanning for IOCs and false positive groups
                potential_secrets, false_positives = regex_for_secrets(line)
                for potential_secret in potential_secrets:
                    if not any(white_list_string in potential_secret for white_list_string in secrets_white_list):
                        regex_secrets.append(potential_secret)
                # added false positives into white list array before testing the strings in line
                secrets_white_list = secrets_white_list.union(false_positives)

                # calculate entropy for each string in the file
                for string_ in line.split():
                    string_ = string_.strip("\"()[],'><:;\\")
                    string_lower = string_.lower()
                    # compare the lower case of the string against both generic whitelist & temp white list
                    if not any(white_list_string in string_lower for white_list_string in secrets_white_list):
                        entropy = calculate_shannon_entropy(string_)
                        if entropy >= ENTROPY_THRESHOLD:
                            high_entropy_strings.append(string_)

        if high_entropy_strings or regex_secrets:
            # uniquify identical matches between lists
            file_secrets = list(set(high_entropy_strings + regex_secrets))
            secrets_found[file_name] = file_secrets

    return secrets_found


def create_temp_white_list(file_contents):
    temp_white_list = set([])
    context_paths = re.findall(r'contextPath: (\S+\.+\S+)', file_contents)
    for context_path in context_paths:
        context_path = context_path.split('.')
        context_path = [white_item.lower() for white_item in context_path]
        temp_white_list = temp_white_list.union(context_path)

    return temp_white_list


def retrieve_related_yml(file_path_temp):
    matching_yml_file_contents = None
    yml_file = file_path_temp + '.yml'
    if os.path.exists(yml_file):
        with io.open('./' + yml_file, mode="r", encoding="utf-8") as matching_yml_file:
            matching_yml_file_contents = matching_yml_file.read()
    return matching_yml_file_contents


def regex_for_secrets(file_contents):
    """Scans for IOCs with potentially low entropy score
    :param file_contents: file to test as string representation (string)
    :return  potential_secrets (list) IOCs found via regex, false_positives (list) Non secrets with high entropy
    """
    potential_secrets = []
    false_positives = []

    # URL REGEX
    urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\), ]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', file_contents)
    if urls:
        potential_secrets += urls
    # EMAIL REGEX
    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', file_contents)
    if emails:
        potential_secrets += emails
    # IPV6 REGEX
    ipv6_list = re.findall(r'(?:(?:[0-9A-Fa-f]{1,4}:){6}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:(?:[0-9]|[1-9][0-9]|1'
                           r'[0-9]{2}|2[0-4][0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))|::'
                           r'(?:[0-9A-Fa-f]{1,4}:){5}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:(?:[0-9]|[1-9][0-9]|1[0-9]'
                           r'{2}|2[0-4][0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))|'
                           r'(?:[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){4}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|'
                           r'(?:(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}'
                           r'|2[0-4][0-9]|25[0-5]))|(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){3}'
                           r'(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])'
                           r'\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))|(?:(?:[0-9A-Fa-f]{1,4}:){,2}'
                           r'[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){2}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|'
                           r'(?:(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}'
                           r'|2[0-4][0-9]|25[0-5]))|(?:(?:[0-9A-Fa-f]{1,4}:){,3}[0-9A-Fa-f]{1,4})?::[0-9A-Fa-f]{1,4}:'
                           r'(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4]'
                           r'[0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))|(?:(?:[0-9A-Fa-f]'
                           r'{1,4}:){,4}[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:(?:[0-9]|[1-9][0-9]'
                           r'|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\.){3}(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))|'
                           r'(?:(?:[0-9A-Fa-f]{1,4}:){,5}[0-9A-Fa-f]{1,4})?::[0-9A-Fa-f]{1,4}|'
                           r'(?:(?:[0-9A-Fa-f]{1,4}:){,6}[0-9A-Fa-f]{1,4})?::)', file_contents)
    if ipv6_list:
        for ipv6 in ipv6_list:
            if ipv6 != '::':
                potential_secrets.append(ipv6)
    # IPV4 REGEX
    ipv4_list = re.findall(r'(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)',
                           file_contents)
    if ipv4_list:
        potential_secrets += ipv4_list
    # Dates REGEX for false positive preventing since they have high entropy
    dates = re.findall(r'((\d{4}[/.-]\d{2}[/.-]\d{2})[T\s](\d{2}:?\d{2}:?\d{2}:?(\.\d{5,6})?([+-]\d{2}:?\d{2})?Z?)?)',
                       file_contents)
    if dates:
        false_positives += [date[0] for date in dates]

    return potential_secrets, false_positives


def calculate_shannon_entropy(data):
    """Algorithm to determine the randomness of a given data.
    Higher is more random/complex, most English words will yield result of around 3+-
    :param data: could be either a list/dict or a string.
    :return: entopry: entropy score.
    """
    if not data:
        return 0
    entropy = 0
    # each unicode code representation of all characters which are considered printable
    for x in (ord(c) for c in string.printable):
        # probability of event X
        px = float(data.count(chr(x))) / len(data)
        if px > 0:
            # the information in every possible news, in bits
            entropy += - px * math.log(px, 2)
    return entropy


def main():
    '''
    This script runs both in a local and a remote environment. In a local environment we don't have any
    logger assigned, and then pykwalify raises an error, since it is logging the validation results.
    Therefore, if we are in a local env, we set up a logger. Also, we set the logger's level to critical
    so the user won't be disturbed by non critical loggings
    '''
    branches = run_git_command("git branch")
    branch_name_reg = re.search("\* (.*)", branches)
    branch_name = branch_name_reg.group(1)

    parser = argparse.ArgumentParser(description='Utility CircleCI usage')
    parser.add_argument('-c', '--circle', type=str2bool, help='Is CircleCi or not')
    options = parser.parse_args()
    is_circle = options.circle
    if is_circle is None:
        is_circle = False

    print_color("Starting validating files structure", LOG_COLORS.GREEN)
    validate_conf_json()
    if branch_name != 'master':
        import logging
        logging.basicConfig(level=logging.CRITICAL)

        # validates only committed files
        validate_committed_files(branch_name, is_circle)
    else:
        # validates all of Content repo directories according to their schemas
        validate_all_files()
    print_color("Finished validating files structure", LOG_COLORS.GREEN)
    sys.exit(0)


if __name__ == "__main__":
    main()
