#!/usr/bin/env python
import click
import sys
import re
import subprocess
import logging
import json
from pprint import pprint


# Logging setup
log = logging.getLogger(__name__)
root = logging.getLogger()
root.setLevel(logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s: %(levelname)s %(message)s')
ch.setFormatter(formatter)
root.addHandler(ch)


@click.command()
@click.option('--live/--no-live', help="Will really kill applications/instances", default=False)
@click.option('--aws-profile', help="AWS profile to use when executing aws cli.", default="klue-publish")
@click.option('--kill-oldest-instance/--no-kill-oldest-instance', help="Kill or not the oldest EC2 instance in each live environment.", default=False)
def main(live, aws_profile, kill_oldest_instance):
    """Remove swaped-out elasticbean applications and optionaly kill the oldest
    instance in each live environment, as a cheap insurance against ressource
    leaks.
    """

    out = subprocess.check_output("aws elasticbeanstalk describe-environments --profile %s" % aws_profile, shell=True)
    environments = json.loads(out.decode("utf-8"))

    for env in environments['Environments']:
        application_name = env['ApplicationName']
        environment_name = env['EnvironmentName']
        version_label = env['VersionLabel']
        cname = env['CNAME']
        status = env['Status']

        log.info("Found environment %s/%s with CNAME %s" % (application_name, version_label, cname))

        if status != 'Ready':
            log.info("Environment is in status %s - Ignoring it." % status)
            continue

        if re.match('^%s-\d{6}-\d{4}-\d+\.' % application_name, cname):
            log.info("Environment is not live - Terminating it!")
            cmd = "aws elasticbeanstalk terminate-environment --environment-name %s --profile %s" % (environment_name, aws_profile)
            if live:
                out = subprocess.check_output(cmd, shell=True)
                pprint(json.loads(out.decode("utf-8")))
            else:
                log.debug("TEST MODE! would execute '%s'" % cmd)
            continue

        log.info("Environment is live - Examining its instances...")
        cmd = "aws elasticbeanstalk describe-environment-resources --environment-name %s --profile %s" % (environment_name, aws_profile)
        out = subprocess.check_output(cmd, shell=True)
        ressources = json.loads(out.decode("utf-8"))
        instances = ressources['EnvironmentResources']['Instances']

        instance_ids = [i['Id'] for i in instances]
        cmd = "aws ec2 describe-instances --instance-ids %s --profile %s" % (' '.join(instance_ids), aws_profile)
        out = subprocess.check_output(cmd, shell=True)
        status_info = json.loads(out.decode("utf-8"))

        launchtime_to_id = {}

        for res in status_info['Reservations']:
            for info in res['Instances']:
                # pprint(info)
                launchtime = info['LaunchTime']
                id = info['InstanceId']
                state = info['State']['Name']

                if state.lower() != 'running':
                    log.info("Instance %s is in state %s - Ignoring it." % (id, state))
                    continue

                log.info("Instance %s was launched at %s (state: %s)" % (id, launchtime, state))
                launchtime_to_id[launchtime] = id

        count_running = len(list(launchtime_to_id.keys()))
        if count_running < 2:
            log.info("Environment has only %s running instances - Not touching them." % count_running)
            continue

        if kill_oldest_instance:
            keys = list(launchtime_to_id.keys())
            keys.sort()
            launchtime_oldest = keys[0]
            id_oldest = launchtime_to_id[launchtime_oldest]

            if live:
                log.info("Killing instance %s launched at %s" % (id_oldest, launchtime_oldest))
                cmd = "aws ec2 terminate-instances --instance-ids %s --profile %s" % (id_oldest, aws_profile)
                out = subprocess.check_output(cmd, shell=True)
                pprint(json.loads(out.decode("utf-8")))
            else:
                log.debug("TEST MODE! Would kill instance %s launched at %s" % (id_oldest, launchtime_oldest))


if __name__ == "__main__":
    main()
