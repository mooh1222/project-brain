namespace runtime {

int transform(int value) {
    return value + 1;
}

int dispatch(int value) {
    return transform(value);
}

int run() {
    return dispatch(41);
}

}
