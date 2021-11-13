pipeline {
    agent {
        docker {
            label '!windows'
            image 'python:3.9.7'
            args '--user 0:1000'
        } 
    }
    stages {
        stage('build') {
            steps {
                sh 'whoami'
                sh 'ls -l'
                sh 'python setup.py sdist bdist_wheel'
            }
        }
        stage('test') {
            steps {
                sh 'pip install dist/tscutter-0.1.$BUILD_NUMBER-py3-none-any.whl'
                sh 'python -m tscutter.analyze -h'
                sh 'python -m tscutter.audio -h'
            }
        }
        stage('deploy') {
            steps {
                sh 'ls -l'
                sh 'pip install twine'
                withCredentials([usernamePassword(credentialsId: '65ddf05a-75ed-43cd-ab7e-5ac1e6af2526', usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD')]) {
                    sh 'twine upload -r testpypi dist/* -u $USERNAME -p $PASSWORD'
                }
            }
        }
    }
}
