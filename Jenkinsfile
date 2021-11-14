pipeline {
    agent {
        docker {
            label '!windows'
            image 'python:3.9.7'
            args '-e HOME=/var/jenkins_home -v /var/jenkins_home:/var/jenkins_home:'
        } 
    }
    stages {
        stage('Build') {
            steps {
                sh '''
                    python --version
                    pwd
                    ls -l
                '''
                sh 'python setup.py sdist bdist_wheel'
            }
        }
        stage('Test') {
            steps {
                sh 'pip install dist/tscutter-0.1.$BUILD_NUMBER-py3-none-any.whl'
                sh 'python -m tscutter.analyze -h'
                sh 'python -m tscutter.audio -h'
            }
        }
        /*stage('Deploy') {
            steps {
                sh 'pip install twine'
                withCredentials([usernamePassword(credentialsId: '65ddf05a-75ed-43cd-ab7e-5ac1e6af2526', usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD')]) {
                    sh 'python -m twine upload -r testpypi dist/* -u $USERNAME -p $PASSWORD'
                }
            }
        }*/
    }
    post {
        aborted {
            echo 'aborted'
            emailext subject: "ABORTED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
                body: """
                    <p>Check console output at &QUOT;<a href='${env.BUILD_URL}'>${env.JOB_NAME} [${env.BUILD_NUMBER}]</a>&QUOT;</p>
                    """,
                recipientProviders: [[$class: 'DevelopersRecipientProvider'], [$class: 'RequesterRecipientProvider']]
        }
        failure {
            echo 'failure'
            emailext subject: "FAILED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
                body: """
                    <p>Check console output at &QUOT;<a href='${env.BUILD_URL}'>${env.JOB_NAME} [${env.BUILD_NUMBER}]</a>&QUOT;</p>
                    """,
                recipientProviders: [[$class: 'DevelopersRecipientProvider'], [$class: 'RequesterRecipientProvider']]
        }
        success {
            echo 'success'
            emailext subject: "SUCCEEDED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
                body: """
                    <p>Check console output at &QUOT;<a href='${env.BUILD_URL}'>${env.JOB_NAME} [${env.BUILD_NUMBER}]</a>&QUOT;</p>
                    """,
                recipientProviders: [[$class: 'DevelopersRecipientProvider'], [$class: 'RequesterRecipientProvider']]
        }
        cleanup {
            echo 'Cleaning up ...'
            sh '''
                rm -rf /var/jenkins_home/.cache/pip
                rm -rf /var/jenkins_home/.local
            '''
        }
    }
}
